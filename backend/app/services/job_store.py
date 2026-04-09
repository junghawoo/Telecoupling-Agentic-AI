"""
Telecoupling AI - In-Memory Job Store

Tracks agent job lifecycle for the lifetime of the server process.
Can be replaced with a Redis/DB-backed store later without changing the API.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.models.agent import ChatMessage, JobStatus, ToolCallRecord

# ------------------------------------------------------------------
# Global in-memory store  (single-process, non-persistent)
# ------------------------------------------------------------------
_store: dict[str, JobStatus] = {}
_MAX_JOBS = 200  # prune oldest when limit is exceeded


def create_job(messages: list[ChatMessage], job_id: str | None = None) -> JobStatus:
    jid = job_id or str(uuid.uuid4())
    job = JobStatus(
        job_id=jid,
        status="pending",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        messages=list(messages),
    )
    _store[jid] = job
    _prune()
    return job


def get_job(job_id: str) -> JobStatus | None:
    return _store.get(job_id)


def list_jobs(limit: int = 50) -> list[JobStatus]:
    jobs = sorted(_store.values(), key=lambda j: j.created_at, reverse=True)
    return jobs[:limit]


def set_running(job_id: str) -> None:
    job = _require(job_id)
    job.status = "running"
    job.updated_at = datetime.utcnow()


def add_tool_call(job_id: str, record: ToolCallRecord) -> None:
    job = _require(job_id)
    job.tool_calls.append(record)
    job.updated_at = datetime.utcnow()


def complete_job(job_id: str, response_text: str) -> None:
    job = _require(job_id)
    job.status = "completed"
    job.final_response = response_text
    job.updated_at = datetime.utcnow()


def fail_job(job_id: str, error: str) -> None:
    job = _require(job_id)
    job.status = "failed"
    job.error = error
    job.updated_at = datetime.utcnow()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _require(job_id: str) -> JobStatus:
    job = _store.get(job_id)
    if job is None:
        raise KeyError(f"Job not found: {job_id}")
    return job


def _prune() -> None:
    if len(_store) > _MAX_JOBS:
        oldest = sorted(_store.values(), key=lambda j: j.created_at)
        for job in oldest[: len(_store) - _MAX_JOBS]:
            del _store[job.job_id]
