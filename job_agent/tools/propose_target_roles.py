"""Strands tool: propose_target_roles."""

from __future__ import annotations

from strands import tool

from tools._common import jsonable, run

@tool
def propose_target_roles() -> list:
    """Propose 3-5 target roles from the current profile, with O*NET codes. They are saved as 'proposed';
    the user confirms them on the Roles page before they are used for searching."""
    from services import profile_service

    return jsonable(run(profile_service.propose_roles()))
