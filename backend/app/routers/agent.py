"""
Telecoupling AI - Agent API Router

Endpoints:
  GET  /agent/tools          List all available MCP tools
  GET  /agent/health         Liveness check for each MCP server
  POST /agent/chat           Streaming SSE chat with the agent
  POST /agent/chat/sync      Synchronous chat (waits for full response)
"""

from __future__ import annotations

import json
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.core.dependencies import get_agent
from app.models.agent import AgentStreamEvent, ChatRequest, ChatResponse
from app.services import job_store
from app.services.agent import TelecouplingAgent

router = APIRouter(prefix="/agent", tags=["agent"])


# --------------------------------------------------------------------------
# Tool discovery
# --------------------------------------------------------------------------


@router.get("/tools", summary="List all available MCP tools")
async def list_tools(agent: TelecouplingAgent = Depends(get_agent)):
    tools = agent.mcp_client.list_tools()
    return {
        "count": len(tools),
        "servers": agent.mcp_client.connected_servers,
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.inputSchema,
            }
            for t in tools
        ],
    }


@router.get("/health", summary="Liveness check for each MCP server")
async def mcp_health(agent: TelecouplingAgent = Depends(get_agent)):
    """
    Returns per-server liveness.  A server is healthy when its subprocess is
    running AND its HTTP endpoint responds within 3 seconds.
    """
    status = await agent.mcp_client.health_check()
    all_ok = all(status.values())
    return {
        "healthy": all_ok,
        "servers": status,
    }


# --------------------------------------------------------------------------
# Streaming chat  (Server-Sent Events)
# --------------------------------------------------------------------------


@router.post("/chat", summary="Chat with the agent (streaming SSE)")
async def chat_streaming(
    request: ChatRequest,
    agent: TelecouplingAgent = Depends(get_agent),
):
    """
    Returns a Server-Sent Events stream.  Each event is a JSON-encoded
    `AgentStreamEvent` with `type` in:
      - `thinking`    – model is reasoning (iteration counter)
      - `tool_call`   – model invoked a tool
      - `tool_result` – tool returned a result
      - `response`    – final answer (stream complete)
      - `error`       – unrecoverable error
    """
    job_id = request.job_id or str(uuid.uuid4())
    job_store.create_job(request.messages, job_id=job_id)

    async def event_stream() -> AsyncGenerator[str, None]:
        job_store.set_running(job_id)
        try:
            async for event in agent.run(request.messages, job_id):
                yield f"data: {event.model_dump_json()}\n\n"

                if event.type == "tool_call":
                    pass  # result not yet available; recorded after tool_result arrives

                elif event.type == "tool_result":
                    from app.models.agent import ToolCallRecord
                    job_store.add_tool_call(job_id, ToolCallRecord(
                        tool=event.data.get("tool", ""),
                        arguments=event.data.get("arguments", {}),
                        result=event.data.get("preview", ""),
                        success=event.data.get("success", False),
                        duration_ms=event.data.get("duration_ms", 0),
                    ))

                elif event.type == "response":
                    job_store.complete_job(job_id, response_text=event.data.get("text", ""))

                elif event.type == "error":
                    job_store.fail_job(job_id, event.data.get("message", "unknown error"))

            # Signal stream end to the client
            yield "data: [DONE]\n\n"

        except Exception as exc:
            err = AgentStreamEvent(type="error", data={"message": str(exc)})
            yield f"data: {err.model_dump_json()}\n\n"
            job_store.fail_job(job_id, str(exc))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Job-ID": job_id,
        },
    )


# --------------------------------------------------------------------------
# Synchronous chat  (waits for completion)
# --------------------------------------------------------------------------


@router.post("/chat/sync", response_model=ChatResponse, summary="Chat with the agent (sync)")
async def chat_sync(
    request: ChatRequest,
    agent: TelecouplingAgent = Depends(get_agent),
):
    """
    Runs the full agent loop and returns when the model has produced its final
    answer.  Suitable for short queries; use `/agent/chat` (SSE) for long-running
    model runs to avoid gateway timeouts.
    """
    job_id = request.job_id or str(uuid.uuid4())
    job_store.create_job(request.messages, job_id=job_id)
    job_store.set_running(job_id)

    final_text = ""
    all_tool_calls = []

    try:
        async for event in agent.run(request.messages, job_id):
            if event.type == "response":
                final_text = event.data.get("text", "")
                all_tool_calls = event.data.get("tool_calls", [])
            elif event.type == "error":
                job_store.fail_job(job_id, event.data.get("message", ""))
                raise HTTPException(status_code=500, detail=event.data.get("message"))
    except HTTPException:
        raise
    except Exception as exc:
        job_store.fail_job(job_id, str(exc))
        raise HTTPException(status_code=500, detail=str(exc))

    job_store.complete_job(job_id, response_text=final_text)
    return ChatResponse(job_id=job_id, text=final_text, tool_calls=all_tool_calls)
