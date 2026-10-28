"""Strands tool: build_my_profile."""

from __future__ import annotations

from strands import tool

from tools._common import jsonable, run

@tool
def build_my_profile() -> dict:
    """Build a new profile version from the primary CV, its notes, LinkedIn sources, selected GitHub repos
    (company repos only as allowed) and manual projects. Uses the LLM; no paid source credits."""
    from services import profile_service

    p = run(profile_service.build_profile())
    prof = p["profile"]
    return jsonable({"version": p["version"], "current_title": prof.get("current_title"),
                     "years": prof.get("total_years_experience"), "skills": prof.get("skills", [])[:25],
                     "projects": [x.get("name") for x in prof.get("projects", [])],
                     "preferences": prof.get("preferences"), "open_questions": prof.get("open_questions")})
