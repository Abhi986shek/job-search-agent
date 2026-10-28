"""Strands tool: search_company_jobs."""

from __future__ import annotations

from strands import tool

from tools._common import jsonable, run

@tool
def search_company_jobs(domain: str) -> dict:
    """List all open jobs at one company from PredictLeads (1 credit). Use when the user names a target company.

    Args:
        domain: Company website domain, e.g. "razorpay.com".
    """
    from services import search_service

    res = run(search_service.company_jobs(domain, 100))
    return jsonable({"summary": res["summary"],
                     "jobs": [{"id": j["id"], "title": j["title"], "location": j["location"]} for j in res["jobs"]]})
