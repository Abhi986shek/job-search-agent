"""SerpApi Google Jobs engine. Returns listings Google indexed, including portal postings (Naukri, Indeed, ...).

Each page is one SerpApi search credit. The key travels as a query parameter, so
errors are reported through utils.safe_error, which never includes the URL.
"""

from __future__ import annotations

import httpx

from config import settings
from schemas import NormalizedJob, SourceResult, UsageEvent
from utils import logger, safe_error, sha256_text

SOURCE = "serpapi"
SEARCH_URL = "https://serpapi.com/search.json"
ACCOUNT_URL = "https://serpapi.com/account.json"


def configured() -> bool:
    return settings.serpapi_configured


def _apply_link(job: dict) -> str:
    options = job.get("apply_options") or []
    for opt in options:
        if isinstance(opt, dict) and opt.get("link"):
            return opt["link"]
    related = job.get("related_links") or []
    for link in related:
        if isinstance(link, dict) and link.get("link"):
            return link["link"]
    return job.get("share_link") or ""


def _normalize(job: dict) -> NormalizedJob | None:
    title = (job.get("title") or "").strip()
    if not title:
        return None
    ext = job.get("detected_extensions") or {}
    via = (job.get("via") or "").removeprefix("via ").strip()
    apply_url = _apply_link(job)
    job_id = job.get("job_id") or sha256_text(f"{title}|{job.get('company_name')}|{apply_url}")
    return NormalizedJob(
        source=SOURCE,
        source_job_id=str(job_id)[:500],
        title=title,
        company=job.get("company_name") or "",
        location=job.get("location") or "",
        description=job.get("description") or "",
        posted_text=ext.get("posted_at") or "",
        apply_url=apply_url,
        source_url=job.get("share_link") or apply_url,
        salary_text=ext.get("salary") or "",
        employment_type=ext.get("schedule_type") or "",
        via=via,
        raw=job,
    )


async def search(query: str, location: str, *, limit: int, gl: str = "in") -> SourceResult:
    if not configured():
        return SourceResult(source=SOURCE, status="not_configured", message="SERPAPI_API_KEY not set")
    if not query:
        return SourceResult(source=SOURCE, status="skipped", message="No query")
    # Location goes into q: SerpApi's `location` parameter needs its canonical names.
    q = f"{query} {location}".strip()
    params = {"engine": "google_jobs", "q": q, "gl": gl, "hl": "en", "api_key": settings.SERPAPI_API_KEY}
    jobs: list[NormalizedJob] = []
    usage: list[UsageEvent] = []
    pages = max(1, settings.SERPAPI_MAX_PAGES)
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            for _ in range(pages):
                resp = await client.get(SEARCH_URL, params=params)
                usage.append(UsageEvent(source=SOURCE, endpoint="google_jobs", status_code=resp.status_code,
                                        credits_used=1))
                data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                if data.get("error"):
                    err = str(data["error"])
                    if "hasn't returned any results" in err:
                        break
                    return SourceResult(source=SOURCE, status="error", message=err[:300], jobs=jobs,
                                        fetched=len(jobs), usage=usage)
                resp.raise_for_status()
                for raw in data.get("jobs_results") or []:
                    nj = _normalize(raw)
                    if nj:
                        jobs.append(nj)
                token = (data.get("serpapi_pagination") or {}).get("next_page_token")
                if not token or len(jobs) >= limit:
                    break
                params["next_page_token"] = token
    except Exception as exc:  # noqa: BLE001
        msg = safe_error(exc)
        logger.warning("serpapi search failed: %s", msg)
        return SourceResult(source=SOURCE, status="error", message=msg, jobs=jobs, fetched=len(jobs), usage=usage)
    jobs = jobs[:limit]
    return SourceResult(source=SOURCE, status="ok", jobs=jobs, fetched=len(jobs), usage=usage)


async def account() -> dict:
    """GET /account.json: plan and searches left this month (does not use a search credit)."""
    if not configured():
        return {"configured": False}
    try:
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
            resp = await client.get(ACCOUNT_URL, params={"api_key": settings.SERPAPI_API_KEY})
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return {"configured": True, "error": safe_error(exc)}
    return {"configured": True, "plan": data.get("plan_name"),
            "searches_per_month": data.get("searches_per_month"),
            "remaining": data.get("total_searches_left"),
            "used_this_month": data.get("this_month_usage")}
