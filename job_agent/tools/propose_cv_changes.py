"""Strands tool: propose_cv_changes."""

from __future__ import annotations

from strands import tool

from tools._common import jsonable, run

@tool
def propose_cv_changes(job_group_id: int | None = None, job_id: int | None = None) -> dict:
    """Create CV change proposals for a job group or one job. Nothing is applied: the user approves each change
    in the app before a CV is generated.

    Args:
        job_group_id: Job group to tailor for.
        job_id: A single job to tailor for (when it needs its own CV).
    """
    from services import cv_service

    v = run(cv_service.propose_changes(job_group_id=job_group_id, job_id=job_id))
    return jsonable({"cv_version_id": v["id"], "proposals": [
        {"id": p["id"], "type": p["change_type"], "section": p["section"], "from": p["original_text"],
         "to": p["proposed_text"], "reason": p["reason"]} for p in v["proposals"]],
        "note": "Ask the user to review and approve these on the CV page."})
