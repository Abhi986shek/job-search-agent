"""Strands tool: add_job_url_for_guidance."""

from __future__ import annotations

from strands import tool

from tools._common import jsonable, run

@tool
def add_job_url_for_guidance(url: str, title: str = "", company: str = "", location: str = "",
                             description: str = "", note: str = "") -> dict:
    """Save a job link the user found (Naukri, LinkedIn, any portal). The page is never fetched;
    only the text the user gives is stored.

    Args:
        url: The job posting link.
        title: Job title, if known.
        company: Company name, if known.
        location: Location, if known.
        description: Job description text pasted by the user.
        note: The user's note about this job.
    """
    from services import search_service
    from utils import is_http_url

    if not is_http_url(url):
        return {"error": "Not a valid http(s) URL"}
    rows = search_service.add_guidance_urls([{"url": url, "title": title, "company": company, "location": location,
                                              "pasted_description": description, "note": note}])
    return jsonable(rows[0])
