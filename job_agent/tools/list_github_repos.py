"""Strands tool: list_github_repos."""

from __future__ import annotations

from strands import tool

from tools._common import jsonable


@tool
def list_github_repos() -> list[dict]:
    """List the owner's synced GitHub repos from both accounts (personal and office): whether each is selected
    for the profile, whether its content may be read, language and description. Read-only."""
    from services import repo_reader

    return jsonable(repo_reader.list_repos())
