"""Strands tool: read_github_repo."""

from __future__ import annotations

from strands import tool

from tools._common import jsonable, run


@tool
def read_github_repo(full_name: str) -> dict:
    """Read one GitHub repo: README opening, languages, file tree, dependency files, Python imports and the AWS and
    framework names found in its code. Use it to answer what a repo does or uses. Read-only. Office repos only when
    their content is allowed.

    Args:
        full_name: Owner and repo, e.g. "Abhi986shek/Zuno-Strands-Agent".
    """
    from services import repo_reader

    return jsonable(run(repo_reader.read_repo(full_name)))
