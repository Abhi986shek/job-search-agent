"""Strands tool: get_profile_inputs."""

from __future__ import annotations

from strands import tool

from tools._common import jsonable, run

@tool
def get_profile_inputs() -> dict:
    """Show every input the profile is built from: CVs and their notes, LinkedIn sources, personal and company
    GitHub repos (selected or not, with the user's commit counts), manual projects, and whether a profile exists."""
    from db import profile_repository as prepo

    cvs = prepo.list_cvs()
    repos = prepo.list_github_repos()

    def repo_view(r: dict) -> dict:
        return {"id": r["id"], "name": r["full_name"], "selected": r["is_selected"],
                "content_allowed": r["account_type"] == "personal" or r["llm_allowed"],
                "my_commits": r["my_commit_count"], "language": r["primary_language"]}

    profile = prepo.get_current_profile()
    return jsonable({
        "cvs": [{"id": c["id"], "file": c["file_name"], "primary": c["is_primary"], "text_chars": c["text_chars"],
                 "notes": [n["note"] for n in c["notes"]]} for c in cvs],
        "linkedin_sources": [{"id": s["id"], "type": s["source_type"], "fetched_at": s["fetched_at"]}
                             for s in prepo.list_linkedin_sources()],
        "github_personal": {"total": sum(r["account_type"] == "personal" for r in repos),
                            "selected": [repo_view(r) for r in repos if r["account_type"] == "personal" and r["is_selected"]]},
        "github_company": {"total": sum(r["account_type"] == "company" for r in repos),
                           "selected": [repo_view(r) for r in repos if r["account_type"] == "company" and r["is_selected"]]},
        "manual_projects": [{"id": p["id"], "title": p["title"]} for p in prepo.list_manual_projects()],
        "profile": ({"version": profile["version"], "built_at": profile["created_at"]} if profile else None),
    })
