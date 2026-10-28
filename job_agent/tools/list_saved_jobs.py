"""Strands tool: list_saved_jobs."""

from __future__ import annotations

from strands import tool

from tools._common import jsonable, run

@tool
def list_saved_jobs(status: str = "", source: str = "", text: str = "", limit: int = 50) -> dict:
    """List jobs already saved in the database.

    Args:
        status: Filter: new, shortlisted, applied, rejected or archived. Empty for all.
        source: Filter: predictleads, serpapi, adzuna, ats or guidance. Empty for all.
        text: Match in title, company or location.
        limit: Max rows.
    """
    from db import repositories as repo

    res = repo.list_jobs(status=status or None, source=source or None, q=text or None, limit=min(limit, 200))
    return jsonable({"total": res["total"], "jobs": [
        {"id": j["id"], "title": j["title"], "company": j["company"], "location": j["location"],
         "status": j["status"], "sources": j["source_names"], "via": j["via"]} for j in res["items"]]})
