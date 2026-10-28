"""Strands tool: find_job_contacts."""

from __future__ import annotations

from strands import tool

from tools._common import jsonable, run

@tool
def find_job_contacts(job_id: int) -> dict:
    """Find people to contact for a job: emails written in the posting, saved contacts, and Apollo search results
    (names and titles only; revealing an email is a separate paid action the user does in the app).

    Args:
        job_id: Job ID.
    """
    from db import outreach_repository as orepo
    from services import outreach_service

    from_posting = outreach_service.contacts_from_posting(job_id)
    try:
        apollo = run(outreach_service.apollo_search(job_id))["people"]
    except Exception as exc:  # noqa: BLE001
        apollo = [{"error": str(exc)}]
    return jsonable({"saved_contacts": orepo.job_contacts(job_id), "from_posting": len(from_posting),
                     "apollo_candidates": apollo[:10]})
