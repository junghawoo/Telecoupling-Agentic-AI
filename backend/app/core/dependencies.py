"""
Telecoupling AI - FastAPI Dependency Providers
"""

from __future__ import annotations

from fastapi import HTTPException

from app.core.state import app_state
from app.services.agent import TelecouplingAgent
from app.services.mcp_client import MCPClient


def get_mcp_client() -> MCPClient:
    if app_state.mcp_client is None:
        raise HTTPException(status_code=503, detail="MCP client not initialised")
    return app_state.mcp_client


def get_agent() -> TelecouplingAgent:
    if app_state.agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialised")
    return app_state.agent
