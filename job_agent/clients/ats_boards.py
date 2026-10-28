"""Public ATS job boards: Greenhouse, Lever, Ashby. Free, no keys; one call per company board.

You register boards (provider + board token) in the app. A board token is the
company slug in its careers URL, e.g. boards.greenhouse.io/<token>, jobs.lever.co/<token>,
jobs.ashbyhq.com/<token>.
"""

from __future__ import annotations

import re

import httpx

from config import settings
from schemas import NormalizedJob, SourceResult, UsageEvent
from utils import normalize_text, parse_datetime, safe_error

SOURCE = "ats"
PROVIDERS = ("greenhouse", "lever", "ashby")


def _strip_html(text: str) -> str:
    import html
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(text or ""))).strip()


def _greenhouse(board: str, company: str, data: dict) -> list[NormalizedJob]:
    out = []
    for j in data.get("jobs") or []:
        out.append(NormalizedJob(
            source=SOURCE, source_job_id=f"greenhouse:{board}:{j.get('id')}", title=j.get("title") or "",
            company=company, location=(j.get("location") or {}).get("name") or "",
            description=_strip_html(j.get("content") or ""), posted_at=parse_datetime(j.get("updated_at")),
            posted_text=(j.get("updated_at") or "")[:10], apply_url=j.get("absolute_url") or "",
            source_url=j.get("absolute_url") or "", via="Greenhouse", raw=j))
    return out


def _lever(board: str, company: str, data: list) -> list[NormalizedJob]:
    out = []
    for j in data or []:
        cats = j.get("categories") or {}
        from datetime import datetime, timezone
        created = j.get("createdAt")
        posted = (datetime.fromtimestamp(created / 1000, tz=timezone.utc).replace(tzinfo=None)
                  if isinstance(created, (int, float)) else None)
        out.append(NormalizedJob(
            source=SOURCE, source_job_id=f"lever:{board}:{j.get('id')}", title=j.get("text") or "",
            company=company, location=cats.get("location") or "",
            description=j.get("descriptionPlain") or _strip_html(j.get("description") or ""),
            posted_at=posted, posted_text=posted.strftime("%Y-%m-%d") if posted else "",
            apply_url=j.get("applyUrl") or j.get("hostedUrl") or "", source_url=j.get("hostedUrl") or "",
            employment_type=cats.get("commitment") or "", via="Lever", raw=j))
    return out


def _ashby(board: str, company: str, data: dict) -> list[NormalizedJob]:
    out = []
    for j in data.get("jobs") or []:
        if j.get("isListed") is False:
            continue
        out.append(NormalizedJob(
            source=SOURCE, source_job_id=f"ashby:{board}:{j.get('id') or j.get('jobUrl')}", title=j.get("title") or "",
            company=company, location=j.get("location") or "",
            description=j.get("descriptionPlain") or _strip_html(j.get("descriptionHtml") or ""),
            posted_at=parse_datetime(j.get("publishedAt")), posted_text=(j.get("publishedAt") or "")[:10],
            apply_url=j.get("applyUrl") or j.get("jobUrl") or "", source_url=j.get("jobUrl") or "",
            employment_type=j.get("employmentType") or "", via="Ashby", raw=j))
    return out


async def fetch_board(provider: str, board_token: str, company_name: str, query: str = "") -> SourceResult:
    urls = {
        "greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true",
        "lever": f"https://api.lever.co/v0/postings/{board_token}?mode=json",
        "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{board_token}",
    }
    if provider not in urls:
        return SourceResult(source=SOURCE, status="error", message=f"Unknown ATS provider {provider}")
    try:
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS, follow_redirects=True) as client:
            resp = await client.get(urls[provider])
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        return SourceResult(source=SOURCE, status="error", message=f"{provider}/{board_token}: {safe_error(exc)}",
                            usage=[UsageEvent(source=SOURCE, endpoint=provider, status_code=code)])
    parser = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby}[provider]
    jobs = [j for j in parser(board_token, company_name or board_token, data) if j.title]
    if query:
        words = {w for w in normalize_text(query).split() if len(w) > 2}
        if words:
            jobs = [j for j in jobs if words & set(normalize_text(j.title).split())]
    return SourceResult(source=SOURCE, status="ok", jobs=jobs, fetched=len(jobs),
                        usage=[UsageEvent(source=SOURCE, endpoint=provider, status_code=resp.status_code)])
