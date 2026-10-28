"""Strands tool: search_jobs."""

from __future__ import annotations

from strands import tool

from tools._common import jsonable, run

@tool
def search_jobs(query: str = "", location: str = "", target_role_id: int | None = None,
                sources: list[str] | None = None, max_days_old: int = 30, limit_per_source: int = 25) -> dict:
    """Search for job postings across PredictLeads, SerpApi Google Jobs, Adzuna and the saved ATS boards.

    Results are de-duplicated and saved. Spends source credits, so only call it when the user asks for a search.

    Args:
        query: Job title or keywords, e.g. "python backend developer". Optional if target_role_id is given.
        location: City, e.g. "Bengaluru". Optional.
        target_role_id: ID of a confirmed target role; its title, O*NET codes and location are used.
        sources: Any of "predictleads", "serpapi", "adzuna". Defaults to all three.
        max_days_old: Only jobs posted within this many days.
        limit_per_source: Max jobs per source (1-100).
    """
    from schemas import ALL_SOURCES, SearchRequest
    from services import search_service

    req = SearchRequest(query=query, location=location, target_role_id=target_role_id,
                        sources=sources or list(ALL_SOURCES), max_days_old=max_days_old,
                        limit_per_source=limit_per_source)
    res = run(search_service.run_search(req))
    return jsonable({"search_id": res["search_id"], "sources": res["sources"], "total_jobs": len(res["jobs"]),
                     "jobs": [{"id": j["id"], "title": j["title"], "company": j["company"], "location": j["location"],
                               "via": j["via"]} for j in res["jobs"][:40]]})
