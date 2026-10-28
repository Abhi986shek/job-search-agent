"""Strands tool: get_job_details."""

from __future__ import annotations

from strands import tool

from tools._common import jsonable, run

@tool
def get_job_details(job_id: int) -> dict:
    """Get one saved job with its full description, apply link and every source that listed it.

    Args:
        job_id: Job ID.
    """
    from db import repositories as repo

    job = repo.get_job(job_id)
    if not job:
        return {"error": "Job not found"}
    for s in job["sources"]:
        s.pop("raw", None)
    job["description"] = (job.get("description") or "")[:6000]
    return jsonable(job)
