"""
Telecoupling AI - MCP Client Service

Starts the InVEST and QGIS MCP servers as background subprocesses
(SSE transport), waits for them to be ready, then holds long-lived
ClientSessions for the lifetime of the FastAPI application.

Health-check / auto-restart:
  Every tool call is wrapped in a timeout.  If a call times out, or if the
  subprocess has died/hung, the server is automatically restarted and the
  call is retried once.  This prevents invest-mcp from silently hanging
  after long model runs (e.g. NDR/SDR on a real watershed dataset).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.types import TextContent, Tool

logger = logging.getLogger(__name__)

_APP_ROOT = Path(__file__).resolve().parents[3]   # …/telecoupling-app/
_MCP_ROOT = _APP_ROOT / "mcp-servers"

_CONNECT_TIMEOUT  = 30      # seconds to wait for a server to become ready
_POLL_INTERVAL    = 0.75    # seconds between readiness polls
_TOOL_CALL_TIMEOUT = 420    # seconds before a single tool call is considered hung
_HEALTH_PING_TIMEOUT = 3.0  # seconds for a quick liveness check


class _ServerConnection:
    """Manages one MCP server subprocess + SSE session."""

    def __init__(self, name: str, script: Path, port: int, python: str | None = None) -> None:
        self.name   = name
        self.script = script
        self.port   = port
        self._python = python or sys.executable
        self._proc: asyncio.subprocess.Process | None = None
        self._session: ClientSession | None = None
        self._tools: list[Tool] = []
        self._sse_cm  = None
        self._sess_cm = None
        self._restart_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    async def start(self) -> None:
        """Spawn subprocess, wait until SSE endpoint is reachable, connect."""
        env = dict(os.environ)
        # Force PROJ/GDAL to use the telecoupling conda env's databases.
        conda_prefix = str(Path(sys.executable).parents[1])
        proj_data = str(Path(conda_prefix) / "share" / "proj")
        env["CONDA_PREFIX"] = conda_prefix
        env["PROJ_DATA"]    = proj_data
        env["PROJ_LIB"]     = proj_data
        env["GDAL_DATA"]    = str(Path(conda_prefix) / "share" / "gdal")
        self._proc = await asyncio.create_subprocess_exec(
            self._python, str(self.script),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        logger.info("%s: subprocess started (PID %d)", self.name, self._proc.pid)

        await self._wait_ready()
        await self._connect_session()

    async def stop(self) -> None:
        """Disconnect session then terminate subprocess."""
        try:
            if self._sess_cm:
                await self._sess_cm.__aexit__(None, None, None)
            if self._sse_cm:
                await self._sse_cm.__aexit__(None, None, None)
        except Exception as exc:
            logger.debug("%s: session teardown warning: %s", self.name, exc)
        finally:
            self._session = None
            self._sess_cm = None
            self._sse_cm  = None

        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._proc.kill()
            logger.info("%s: subprocess stopped", self.name)
        self._proc = None

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """
        Call a tool with an automatic timeout + single restart-and-retry on failure.

        Failure modes handled:
          - asyncio.TimeoutError  — server hung, no response within _TOOL_CALL_TIMEOUT
          - Exception during call — session broken (e.g. after server crash)
        """
        try:
            return await asyncio.wait_for(
                self._raw_call(tool_name, arguments),
                timeout=_TOOL_CALL_TIMEOUT,
            )
        except (asyncio.TimeoutError, Exception) as exc:
            logger.warning(
                "%s: tool '%s' failed (%s). Checking health …",
                self.name, tool_name, exc,
            )
            healthy = await self._is_healthy()
            if not healthy:
                logger.warning("%s: unhealthy — attempting auto-restart …", self.name)
                await self._safe_restart()
                logger.info("%s: restarted. Retrying tool '%s' …", self.name, tool_name)
                # Retry once after successful restart
                return await asyncio.wait_for(
                    self._raw_call(tool_name, arguments),
                    timeout=_TOOL_CALL_TIMEOUT,
                )
            # Server is healthy — re-raise the original error
            raise

    async def _raw_call(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if self._session is None:
            raise RuntimeError(f"Not connected to {self.name}")
        result = await self._session.call_tool(tool_name, arguments)
        parts = [c.text for c in result.content if isinstance(c, TextContent)]
        return "\n".join(parts)

    @property
    def tools(self) -> list[Tool]:
        return self._tools

    # ------------------------------------------------------------------
    # Health check & restart
    # ------------------------------------------------------------------

    async def _is_healthy(self) -> bool:
        """
        Returns True when the server process is alive and its HTTP endpoint responds.
        """
        # 1. Process still running?
        if self._proc is None or self._proc.returncode is not None:
            logger.debug("%s: process is not running (rc=%s)", self.name, self._proc and self._proc.returncode)
            return False

        # 2. HTTP endpoint still responding?
        url = f"http://127.0.0.1:{self.port}/"
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(url, timeout=_HEALTH_PING_TIMEOUT)
                if r.status_code < 500:
                    return True
        except Exception as exc:
            logger.debug("%s: health ping failed: %s", self.name, exc)

        return False

    async def _safe_restart(self) -> None:
        """Stop and restart while holding a lock to prevent concurrent restarts."""
        async with self._restart_lock:
            logger.info("%s: stopping for restart …", self.name)
            await self.stop()
            logger.info("%s: starting fresh …", self.name)
            await self.start()
            logger.info("%s: restart complete – %d tools", self.name, len(self._tools))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _wait_ready(self) -> None:
        """Poll the SSE HTTP endpoint until it responds."""
        url = f"http://127.0.0.1:{self.port}/"
        deadline = asyncio.get_event_loop().time() + _CONNECT_TIMEOUT
        async with httpx.AsyncClient() as client:
            while asyncio.get_event_loop().time() < deadline:
                # Check process hasn't died
                if self._proc.returncode is not None:
                    stderr = await self._proc.stderr.read()
                    raise RuntimeError(
                        f"{self.name} exited early (rc={self._proc.returncode}):\n"
                        + stderr.decode()[-2000:]
                    )
                try:
                    r = await client.get(url, timeout=1.0)
                    if r.status_code < 500:
                        logger.info("%s: ready on port %d", self.name, self.port)
                        return
                except Exception:
                    pass
                await asyncio.sleep(_POLL_INTERVAL)
        raise TimeoutError(f"{self.name} did not become ready within {_CONNECT_TIMEOUT}s")

    async def _connect_session(self) -> None:
        sse_url = f"http://127.0.0.1:{self.port}/sse"
        self._sse_cm  = sse_client(sse_url)
        read, write   = await self._sse_cm.__aenter__()
        self._sess_cm = ClientSession(read, write)
        self._session = await self._sess_cm.__aenter__()
        await self._session.initialize()
        result = await self._session.list_tools()
        self._tools = result.tools
        logger.info("%s: connected – %d tools available", self.name, len(self._tools))


# ---------------------------------------------------------------------------
# Public facade
# ---------------------------------------------------------------------------

class MCPClient:
    """
    Aggregates connections to invest-mcp and qgis-mcp.

    Lifecycle (managed by FastAPI lifespan):
        client = MCPClient()
        await client.connect_all()
        ...
        await client.disconnect_all()
    """

    def __init__(self) -> None:
        self._servers: dict[str, _ServerConnection] = {}
        self._tool_to_server: dict[str, str] = {}

    async def connect_all(self) -> None:
        candidates = [
            _ServerConnection(
                "invest-mcp",
                _MCP_ROOT / "invest-mcp" / "server.py",
                int(os.getenv("INVEST_MCP_PORT", 54320)),
            ),
            _ServerConnection(
                "qgis-mcp",
                _MCP_ROOT / "qgis-mcp" / "server.py",
                int(os.getenv("QGIS_MCP_PORT", 54321)),
                python="/usr/bin/python3",   # PyQGIS only in system Python
            ),
        ]
        for srv in candidates:
            try:
                await srv.start()
                self._servers[srv.name] = srv
                for tool in srv.tools:
                    self._tool_to_server[tool.name] = srv.name
            except Exception as exc:
                logger.warning("Could not start %s: %s", srv.name, exc)

        if not self._servers:
            raise RuntimeError("No MCP servers could be started — check logs above.")

        logger.info(
            "MCPClient ready: %d server(s), %d total tools — %s",
            len(self._servers),
            len(self._tool_to_server),
            list(self._servers),
        )

    async def disconnect_all(self) -> None:
        for srv in self._servers.values():
            await srv.stop()
        self._servers.clear()
        self._tool_to_server.clear()

    def list_tools(self) -> list[Tool]:
        tools: list[Tool] = []
        for srv in self._servers.values():
            tools.extend(srv.tools)
        return tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        srv_name = self._tool_to_server.get(tool_name)
        if not srv_name:
            raise ValueError(
                f"Unknown tool '{tool_name}'. Available: {sorted(self._tool_to_server)}"
            )
        return await self._servers[srv_name].call_tool(tool_name, arguments)

    async def health_check(self) -> dict[str, bool]:
        """Return liveness status for each connected server."""
        result: dict[str, bool] = {}
        for name, srv in self._servers.items():
            result[name] = await srv._is_healthy()
        return result

    @property
    def connected_servers(self) -> list[str]:
        return list(self._servers)
