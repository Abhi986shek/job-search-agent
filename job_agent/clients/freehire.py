"""freehire public job search API (keyless, personal and non-commercial use).

Docs: https://freehire.me/docs/api  (GET /jobs/search is the only endpoint used here).

Notes:
- GET /jobs ignores every filter, so only /jobs/search is called.
- freehire carries listings from many sources, including company ATS boards, aggregators and Naukri.
  All are kept by default. FREEHIRE_EXCLUDE_SOURCES can drop named sources client-side.
- This app only reads freehire's API; it never fetches Naukri or any other portal itself.
- The city filter is applied here. The API's cities and metros filters did not narrow results when tested,
  so pages are read (up to FREEHIRE_MAX_PAGES, 100 rows each) until enough jobs pass the filters.
"""

from __future__ import annotations

import html
import re

import httpx

from config import settings
from schemas import NormalizedJob, SourceResult, UsageEvent
from utils import logger, parse_datetime, safe_error

SOURCE = "freehire"
BASE = "https://freehire.me/api/v1/jobs/search"
PAGE_SIZE = 100


def configured() -> bool:
    return True  # public, keyless endpoint


def _excluded_sources() -> set[str]:
    return {s.strip().lower() for s in settings.FREEHIRE_EXCLUDE_SOURCES.split(",") if s.strip()}


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(text or ""))).strip()


def _salary(enrichment: dict) -> str:
    lo, hi = enrichment.get("salary_min"), enrichment.get("salary_max")
    if not (lo or hi):
        return ""
    cur = enrichment.get("salary_currency") or ""
    per = enrichment.get("salary_period") or ""
    return f"{cur} {int(lo) if lo else ''}-{int(hi) if hi else ''} per {per}".strip()


def _normalize(item: dict) -> NormalizedJob | None:
    title = _strip_html(item.get("title") or "")
    slug = item.get("public_slug")
    if not title or not slug:
        return None
    enrichment = item.get("enrichment") or {}
    apply_url = item.get("url") or ""
    return NormalizedJob(
        source=SOURCE,
        source_job_id=slug,
        title=title,
        company=item.get("company") or "",
        location=item.get("location") or "",
        description=_strip_html(item.get("description") or ""),
        posted_at=parse_datetime(item.get("posted_at")),
        posted_text=(item.get("posted_at") or "")[:10],
        apply_url=apply_url,
        source_url=apply_url,
        salary_text=_salary(enrichment),
        employment_type=(enrichment.get("employment_type") or "").replace("_", " "),
        via=f"freehire ({item.get('source') or 'unknown'})",
        raw=item,
    )


def _matches_location(item: dict, location: str) -> bool:
    if not location:
        return True
    wanted = location.strip().lower()
    places = [item.get("location") or ""] + list(item.get("cities") or []) + list(item.get("metros") or [])
    return any(wanted in p.lower() for p in places)


async def search(query: str, location: str, *, limit: int, max_days_old: int) -> SourceResult:
    if not query:
        return SourceResult(source=SOURCE, status="skipped", message="No query")

    excluded = _excluded_sources()
    kept: list[dict] = []
    usage: list[UsageEvent] = []
    total = None
    dropped = 0
    error_msg = ""
    try:
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
            for page in range(max(1, settings.FREEHIRE_MAX_PAGES)):
                params = {
                    "q": query,
                    "countries": settings.FREEHIRE_COUNTRY,
                    "posted_within_days": max_days_old,
                    "sort": "posted_at",
                    "order": "desc",
                    "limit": PAGE_SIZE,
                    "offset": page * PAGE_SIZE,
                }
                resp = await client.get(BASE, params=params)
                usage.append(UsageEvent(source=SOURCE, endpoint="jobs/search", status_code=resp.status_code))
                if resp.status_code == 429:
                    error_msg = f"freehire rate limit reached, retry after {resp.headers.get('Retry-After', 'unknown')} seconds"
                    break
                resp.raise_for_status()
                body = resp.json()
                items = body.get("data") or []
                total = (body.get("meta") or {}).get("total", total)
                for item in items:
                    if (item.get("source") or "").lower() in excluded or not _matches_location(item, location):
                        dropped += 1
                        continue
                    kept.append(item)
                if len(kept) >= limit or len(items) < PAGE_SIZE:
                    break
    except Exception as exc:  # noqa: BLE001
        code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        error_msg = safe_error(exc)
        logger.warning("freehire search failed: %s", error_msg)
        usage.append(UsageEvent(source=SOURCE, endpoint="jobs/search", status_code=code))

    jobs = [j for j in (_normalize(i) for i in kept) if j][:limit]
    if error_msg and not jobs:
        return SourceResult(source=SOURCE, status="error", message=error_msg, usage=usage)
    if usage and total is not None:
        usage[-1].note = f"total matches reported: {total}"
    notes = []
    if dropped:
        notes.append(f"dropped {dropped} off-city or excluded-source results")
    if error_msg:
        notes.append(error_msg)
    return SourceResult(source=SOURCE, status="ok", jobs=jobs, fetched=len(jobs),
                        message="; ".join(notes), usage=usage)
