"""
Telecoupling AI - Application State

Holds singleton references to long-lived services (MCP client, agent).
Populated during FastAPI lifespan startup; imported by routers via dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.agent import TelecouplingAgent
    from app.services.mcp_client import MCPClient


class _AppState:
    mcp_client: "MCPClient | None" = None
    agent: "TelecouplingAgent | None" = None


app_state = _AppState()
