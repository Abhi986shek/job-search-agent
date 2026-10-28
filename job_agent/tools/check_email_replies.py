"""Strands tool: check_email_replies."""

from __future__ import annotations

from strands import tool

from tools._common import jsonable, run

@tool
def check_email_replies() -> dict:
    """Check the user's Gmail for replies, only in threads this app started. New replies are saved and classified."""
    from db import outreach_repository as orepo
    from services import outreach_service

    res = run(outreach_service.check_replies())
    replied = [{"thread_id": t["id"], "job": t["job"]["title"] if t["job"] else None,
                "contact": (t["contact"] or {}).get("full_name")} for t in orepo.list_threads(status="replied")]
    return jsonable({**res, "threads_with_replies": replied})
