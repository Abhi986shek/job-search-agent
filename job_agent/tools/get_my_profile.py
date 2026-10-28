"""Strands tool: get_my_profile."""

from __future__ import annotations

from strands import tool

from tools._common import jsonable, run

@tool
def get_my_profile() -> dict:
    """Read the user's current structured profile (skills, experience, projects, preferences)."""
    from db import profile_repository as prepo

    p = prepo.get_current_profile()
    return jsonable({"version": p["version"], "profile": p["profile"]}) if p else {"error": "No profile built yet"}
