"""Strands tool: draft_outreach_message."""

from __future__ import annotations

from strands import tool

from tools._common import jsonable, run

@tool
def draft_outreach_message(job_id: int, contact_id: int, channel: str = "email") -> dict:
    """Draft an outreach email or LinkedIn message for a job and contact. It is saved as a draft only;
    the user edits, approves and sends it (LinkedIn messages are always sent by the user).

    Args:
        job_id: Job ID.
        contact_id: Contact ID (from find_job_contacts saved_contacts).
        channel: "email" or "linkedin".
    """
    from services import outreach_service

    if channel not in ("email", "linkedin"):
        return {"error": "channel must be email or linkedin"}
    t = run(outreach_service.create_draft(job_id, contact_id, channel))
    m = t["messages"][-1]
    return jsonable({"thread_id": t["id"], "message_id": m["id"], "subject": m["subject"], "body": m["body"],
                     "status": "draft - user must approve in the Outreach page"})
