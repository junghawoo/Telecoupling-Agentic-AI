"""
Telecoupling AI - Jobs API Router

Endpoints:
  GET /jobs           List recent jobs
  GET /jobs/{job_id}  Get a specific job's status and results
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.agent import JobStatus
from app.services import job_store

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobStatus], summary="List recent agent jobs")
async def list_jobs(limit: int = 50):
    return job_store.list_jobs(limit=limit)


@router.get("/{job_id}", response_model=JobStatus, summary="Get job status and results")
async def get_job(job_id: str):
    job = job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return job
