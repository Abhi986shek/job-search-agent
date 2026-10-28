"""Strands tool: list_target_roles."""

from __future__ import annotations

from strands import tool

from tools._common import jsonable, run

@tool
def list_target_roles(status: str = "") -> list:
    """List the user's target roles with their O*NET codes and locations.

    Args:
        status: proposed, confirmed or rejected. Empty for all.
    """
    from db import repositories as repo

    return jsonable(repo.list_roles(status or None))
