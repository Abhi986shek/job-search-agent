"""Adzuna job search API (official). India index by default (ADZUNA_COUNTRY=in)."""

from __future__ import annotations

import re

import httpx

from config import settings
from schemas import NormalizedJob, SourceResult, UsageEvent
from utils import logger, parse_datetime, safe_error

SOURCE = "adzuna"
BASE = "https://api.adzuna.com/v1/api/jobs"


def configured() -> bool:
    return settings.adzuna_configured


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def _normalize(item: dict) -> NormalizedJob | None:
    title = _strip_html(item.get("title") or "")
    if not title:
        return None
    salary = ""
    lo, hi = item.get("salary_min"), item.get("salary_max")
    if lo or hi:
        salary = f"{int(lo) if lo else ''}-{int(hi) if hi else ''}"
        if item.get("salary_is_predicted") in ("1", 1, True):
            salary += " (Adzuna estimate)"
    contract = " ".join(x for x in (item.get("contract_time"), item.get("contract_type")) if x)
    return NormalizedJob(
        source=SOURCE,
        source_job_id=str(item.get("id")),
        title=title,
        company=(item.get("company") or {}).get("display_name") or "",
        location=(item.get("location") or {}).get("display_name") or "",
        description=_strip_html(item.get("description") or ""),
        posted_at=parse_datetime(item.get("created")),
        posted_text=(item.get("created") or "")[:10],
        apply_url=item.get("redirect_url") or "",
        source_url=item.get("redirect_url") or "",
        salary_text=salary,
        employment_type=contract.replace("_", " "),
        via="Adzuna",
        raw=item,
    )


async def search(query: str, location: str, *, limit: int, max_days_old: int) -> SourceResult:
    if not configured():
        return SourceResult(source=SOURCE, status="not_configured", message="ADZUNA_APP_ID/ADZUNA_APP_KEY not set")
    if not query:
        return SourceResult(source=SOURCE, status="skipped", message="No query")
    params = {
        "app_id": settings.ADZUNA_APP_ID,
        "app_key": settings.ADZUNA_APP_KEY,
        "what": query,
        "results_per_page": min(limit, 50),
        "max_days_old": max_days_old,
        "content-type": "application/json",
    }
    if location:
        params["where"] = location
    url = f"{BASE}/{settings.ADZUNA_COUNTRY}/search/1"
    try:
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        msg = safe_error(exc)
        logger.warning("adzuna search failed: %s", msg)
        return SourceResult(source=SOURCE, status="error", message=msg,
                            usage=[UsageEvent(source=SOURCE, endpoint="jobs/search", status_code=code)])
    jobs = [j for j in (_normalize(i) for i in data.get("results") or []) if j][:limit]
    return SourceResult(source=SOURCE, status="ok", jobs=jobs, fetched=len(jobs),
                        usage=[UsageEvent(source=SOURCE, endpoint="jobs/search", status_code=resp.status_code,
                                          credits_used=1, note=f"total matches reported: {data.get('count')}")])
