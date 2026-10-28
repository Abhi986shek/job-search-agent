"""Strands tool: match_jobs_to_profile."""

from __future__ import annotations

from strands import tool

from tools._common import jsonable, run

@tool
def match_jobs_to_profile(job_ids: list[int] | None = None, limit: int = 30) -> dict:
    """Score saved jobs against the user's profile (0-100 with gaps) and group similar jobs for CV tailoring.

    Args:
        job_ids: Specific jobs to score. Empty scores the latest saved jobs.
        limit: Max jobs when job_ids is empty.
    """
    from services import match_service

    res = run(match_service.match_jobs(job_ids=job_ids or None, limit=limit))
    return jsonable({"scored": res["scored"],
                     "groups": [{"id": g["id"], "name": g["name"], "job_ids": g["job_ids"]} for g in res["groups"]],
                     "top": [{"job_id": m["job_id"], "score": m["score"], "title": m["job"]["title"],
                              "company": m["job"]["company"]} for m in res["matches"][:15]]})
