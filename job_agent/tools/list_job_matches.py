"""Strands tool: list_job_matches."""

from __future__ import annotations

from strands import tool

from tools._common import jsonable, run

@tool
def list_job_matches(min_score: int = 0) -> dict:
    """List existing job scores, gaps and job groups for the current profile, without re-scoring.

    Args:
        min_score: Only matches with at least this score (0-100).
    """
    from db import cv_repository as crepo
    from db import profile_repository as prepo

    p = prepo.get_current_profile()
    if not p:
        return {"error": "No profile built yet"}
    matches = crepo.list_matches(p["id"], min_score)
    return jsonable({
        "matches": [{"job_id": m["job_id"], "score": m["score"], "title": m["job"]["title"],
                     "company": m["job"]["company"], "top_gap": (m["gaps"] or [{}])[0].get("gap") if m["gaps"] else None,
                     "job_group_id": m["job_group_id"]} for m in matches[:50]],
        "groups": [{"id": g["id"], "name": g["name"], "jobs": len(g["jobs"])} for g in crepo.list_groups(p["id"])],
    })
