"""
Telecoupling AI - Agent Data Models
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "model"] = "user"
    content: str


class ToolCallRecord(BaseModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: str
    success: bool
    error: str | None = None
    duration_ms: float | None = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    job_id: str | None = None  # Supply to append to an existing job


class ChatResponse(BaseModel):
    job_id: str
    text: str
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)


class AgentStreamEvent(BaseModel):
    """Server-Sent Event payload emitted during agent execution."""

    type: Literal["classified", "thinking", "tool_call", "tool_result", "response", "error"]
    data: dict[str, Any] = Field(default_factory=dict)


class JobStatus(BaseModel):
    job_id: str
    status: Literal["pending", "running", "completed", "failed"]
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    messages: list[ChatMessage] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    final_response: str | None = None
    error: str | None = None
