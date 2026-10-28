"""Read your own LinkedIn posts from the stored LinkedIn data export (Shares.csv).

Nothing is fetched from linkedin.com here. The posts come only from the export you uploaded on the LinkedIn tab,
so a newer post appears after you upload a new export.
"""

from __future__ import annotations

from db import profile_repository as prepo
from services.repo_reader import redact

MAX_POST_CHARS = 1500


def _pick(row: dict, *needles: str) -> str:
    """First value whose column name contains one of the needles (column names can vary by export)."""
    for key, value in row.items():
        if any(n in key.lower() for n in needles) and value not in (None, ""):
            return str(value)
    return ""


def list_posts(limit: int = 5) -> dict:
    limit = max(1, min(int(limit), 20))
    posts: list[dict] = []
    export_found = False
    for src in prepo.list_linkedin_sources(include_raw=True):
        raw = src.get("raw") or {}
        if src.get("source_type") != "export_csv" or "shares" not in raw:
            continue
        export_found = True
        for row in raw.get("shares") or []:
            text = _pick(row, "commentary", "text", "content")
            if not text.strip():
                continue  # a repost or media-only share with no written text
            posts.append({
                "date": _pick(row, "date", "time"),
                "text": redact(text.strip()[:MAX_POST_CHARS]),
                "link": _pick(row, "sharelink", "link", "url"),
                "shared_url": _pick(row, "sharedurl", "shared_url"),
                "truncated": len(text.strip()) > MAX_POST_CHARS,
            })
    if not export_found:
        return {"posts": [], "note": "No LinkedIn export with posts is stored. On the LinkedIn tab, request a fresh "
                                     "LinkedIn data export (it includes Shares.csv) and upload the ZIP."}
    posts.sort(key=lambda p: p["date"], reverse=True)  # ISO-style dates sort correctly as text
    return {"posts": posts[:limit], "total_written_posts": len(posts),
            "note": "Read from your stored LinkedIn export. Newer posts need a new export upload."}
