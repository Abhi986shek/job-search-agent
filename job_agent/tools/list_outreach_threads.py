"""Strands tool: list_outreach_threads."""

from __future__ import annotations

from strands import tool

from tools._common import jsonable, run

@tool
def list_outreach_threads(status: str = "") -> list:
    """List outreach threads with contact, job, channel, status and the latest message.

    Args:
        status: draft, waiting, replied, closed or skipped. Empty for all.
    """
    from db import outreach_repository as orepo

    out = []
    for t in orepo.list_threads(status=status or None):
        last = t["messages"][-1] if t["messages"] else {}
        out.append({"thread_id": t["id"], "status": t["status"], "channel": t["channel"],
                    "job": (t["job"] or {}).get("title"), "company": (t["job"] or {}).get("company"),
                    "contact": (t["contact"] or {}).get("full_name"),
                    "last_message": {"id": last.get("id"), "direction": last.get("direction"),
                                     "status": last.get("status"), "category": last.get("reply_category")}})
    return jsonable(out)
