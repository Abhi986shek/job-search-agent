"""Strands tool: read_github_file."""

from __future__ import annotations

from strands import tool

from tools._common import jsonable, run


@tool
def read_github_file(full_name: str, path: str) -> dict:
    """Read one text file from a GitHub repo (up to 6,000 characters, secrets redacted). Use it after
    read_github_repo to check specific code. Read-only.

    Args:
        full_name: Owner and repo, e.g. "Abhi986shek/Zuno-Strands-Agent".
        path: File path inside the repo, e.g. "agent.py" or "tools/payment.py".
    """
    from services import repo_reader

    return jsonable(run(repo_reader.read_file(full_name, path)))
