"""Strands tool: read_linkedin_posts."""

from __future__ import annotations

from strands import tool

from tools._common import jsonable


@tool
def read_linkedin_posts(limit: int = 5) -> dict:
    """Read the owner's latest written LinkedIn posts from the stored LinkedIn data export (Shares.csv). Read-only.
    Nothing is fetched from LinkedIn; a newer post appears only after a new export is uploaded.

    Args:
        limit: How many of the latest posts to return (1 to 20).
    """
    from services import linkedin_reader

    return jsonable(linkedin_reader.list_posts(limit))
