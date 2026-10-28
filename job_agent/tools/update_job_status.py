"""Strands tool: update_job_status."""

from __future__ import annotations

from strands import tool

from tools._common import jsonable, run

@tool
def update_job_status(job_id: int, status: str) -> dict:
    """Change a job's status.

    Args:
        job_id: Job ID.
        status: One of new, shortlisted, applied, rejected, archived.
    """
    from db import repositories as repo

    if status not in ("new", "shortlisted", "applied", "rejected", "archived"):
        return {"error": "Invalid status"}
    job = repo.update_job_status(job_id, status)
    return jsonable({"id": job["id"], "status": job["status"]}) if job else {"error": "Job not found"}
