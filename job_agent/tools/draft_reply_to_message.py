"""Strands tool: draft_reply_to_message."""

from __future__ import annotations

from strands import tool

from tools._common import jsonable, run

@tool
def draft_reply_to_message(thread_id: int, guidance: str = "") -> dict:
    """Draft the user's next reply in an outreach thread that has a reply. Saved as a draft for approval.

    Args:
        thread_id: Outreach thread ID.
        guidance: What the user wants to say, e.g. "accept the interview, ask for the JD".
    """
    from services import outreach_service

    t = run(outreach_service.draft_reply(thread_id, guidance))
    m = next(x for x in t["messages"] if x["id"] == t["draft_message_id"])
    return jsonable({"thread_id": thread_id, "message_id": m["id"], "subject": m["subject"], "body": m["body"],
                     "check_before_sending": t["notes_for_user"]})
