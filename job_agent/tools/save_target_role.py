"""Strands tool: save_target_role."""

from __future__ import annotations

from strands import tool

from tools._common import jsonable, run

@tool
def save_target_role(title: str, locations: list[str] | None = None, onet_codes: list[str] | None = None,
                     seniority: str = "", remote_ok: bool = False) -> dict:
    """Save a target role as 'proposed'. The user confirms it in the app before it is used for searching.

    Args:
        title: Role title, e.g. "Backend Engineer".
        locations: Cities or "Remote".
        onet_codes: O*NET codes such as 15-1252.00. Suggested automatically if empty.
        seniority: e.g. junior, mid, senior, lead.
        remote_ok: Whether remote jobs are acceptable.
    """
    import onet
    from db import repositories as repo
    from schemas import TargetRoleIn

    codes = onet_codes or [s["code"] for s in onet.suggest(title, 2)]
    data = TargetRoleIn(title=title, locations=locations or [], onet_codes=codes, seniority=seniority,
                        remote_ok=remote_ok, status="proposed")
    return jsonable(repo.create_role(data.model_dump()))
