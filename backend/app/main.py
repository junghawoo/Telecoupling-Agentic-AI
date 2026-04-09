"""
Telecoupling AI - FastAPI Application Entry Point
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.state import app_state

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)


# --------------------------------------------------------------------------
# Lifespan: start / stop MCP servers and agent
# --------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- Startup ----
    logger.info("Starting Telecoupling AI backend…")

    from app.services.mcp_client import MCPClient
    from app.services.agent import TelecouplingAgent

    app_state.mcp_client = MCPClient()
    await app_state.mcp_client.connect_all()

    app_state.agent = TelecouplingAgent(app_state.mcp_client)
    tool_count = len(app_state.mcp_client.list_tools())
    logger.info("Agent ready – %d tools available across %s", tool_count, app_state.mcp_client.connected_servers)

    yield

    # ---- Shutdown ----
    logger.info("Shutting down MCP connections…")
    if app_state.mcp_client:
        await app_state.mcp_client.disconnect_all()
    app_state.mcp_client = None
    app_state.agent = None


# --------------------------------------------------------------------------
# Application
# --------------------------------------------------------------------------


app = FastAPI(
    title="Telecoupling AI",
    description="Agentic AI platform for environmental geospatial analysis using InVEST and QGIS",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------------------------------
# Routers
# --------------------------------------------------------------------------

from app.routers.agent import router as agent_router  # noqa: E402
from app.routers.files import router as files_router  # noqa: E402
from app.routers.jobs import router as jobs_router  # noqa: E402

app.include_router(agent_router)
app.include_router(files_router)
app.include_router(jobs_router)


# --------------------------------------------------------------------------
# Core endpoints
# --------------------------------------------------------------------------


@app.get("/health", tags=["system"])
async def health_check():
    servers = app_state.mcp_client.connected_servers if app_state.mcp_client else []
    tool_count = len(app_state.mcp_client.list_tools()) if app_state.mcp_client else 0
    return {
        "status": "healthy",
        "version": "0.1.0",
        "llm_provider": settings.llm_provider,
        "active_model": settings.active_model,
        "mcp_servers": servers,
        "tool_count": tool_count,
    }


@app.get("/", tags=["system"])
async def root():
    return {
        "message": "Telecoupling AI API",
        "docs": "/docs",
        "health": "/health",
        "endpoints": {
            "tools": "GET /agent/tools",
            "chat_stream": "POST /agent/chat",
            "chat_sync": "POST /agent/chat/sync",
            "jobs": "GET /jobs",
            "job_detail": "GET /jobs/{job_id}",
            "upload_file": "POST /files/upload",
            "list_files": "GET /files",
            "delete_file": "DELETE /files/{filename}",
        },
    }
