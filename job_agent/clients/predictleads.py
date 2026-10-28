"""PredictLeads job openings, called directly over REST (no MCP).

Base URL and auth headers live only in this module. See README section 5.1 for the calls.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx

from config import settings
from schemas import NormalizedJob, SourceResult, UsageEvent
from utils import clean_domain, logger, parse_datetime, safe_error, utcnow

SOURCE = "predictleads"
API_V3_BASE = "https://predictleads.com/api/v3"


def _url(path: str) -> str:
    return f"{API_V3_BASE}{path}"


def _headers() -> dict:
    return {
        "X-Api-Key": settings.PREDICTLEADS_API_KEY,
        "X-Api-Token": settings.PREDICTLEADS_API_TOKEN,
        "Accept": "application/json",
    }


def configured() -> bool:
    return settings.predictleads_configured


def _companies_index(payload: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for item in payload.get("included") or []:
        if isinstance(item, dict) and item.get("type") == "company":
            out[str(item.get("id"))] = item.get("attributes") or {}
    return out


def _location_text(attrs: dict) -> str:
    if isinstance(attrs.get("location"), str) and attrs["location"]:
        return attrs["location"]
    parts = []
    for loc in attrs.get("location_data") or []:
        if isinstance(loc, dict):
            text = ", ".join(p for p in (loc.get("city"), loc.get("state"), loc.get("country")) if p)
            if text:
                parts.append(text)
    return "; ".join(parts)


def _normalize(item: dict, companies: dict[str, dict], fallback_domain: str = "") -> NormalizedJob | None:
    attrs = item.get("attributes") or {}
    title = (attrs.get("title") or "").strip()
    if not title:
        return None
    company_ref = ((item.get("relationships") or {}).get("company") or {}).get("data") or {}
    company_attrs = companies.get(str(company_ref.get("id")), {})
    domain = company_attrs.get("domain") or fallback_domain
    company = company_attrs.get("company_name") or company_attrs.get("friendly_company_name") or domain
    salary = attrs.get("salary")
    salary_text = salary if isinstance(salary, str) else ""
    if not salary_text and attrs.get("salary_data"):
        sd = attrs["salary_data"] or {}
        if isinstance(sd, dict) and (sd.get("salary_low") or sd.get("salary_high")):
            salary_text = f"{sd.get('salary_low') or ''}-{sd.get('salary_high') or ''} {sd.get('salary_currency') or ''}".strip()
    contract = attrs.get("contract_types") or attrs.get("contract_type") or ""
    return NormalizedJob(
        source=SOURCE,
        source_job_id=str(item.get("id")),
        title=title,
        company=company or "",
        company_domain=clean_domain(domain),
        location=_location_text(attrs),
        description=attrs.get("description") or "",
        posted_at=parse_datetime(attrs.get("posted_at") or attrs.get("first_seen_at")),
        posted_text=(attrs.get("posted_at") or attrs.get("first_seen_at") or "")[:10],
        apply_url=attrs.get("url") or "",
        source_url=attrs.get("url") or "",
        salary_text=salary_text,
        employment_type=", ".join(contract) if isinstance(contract, list) else str(contract or ""),
        via="Company careers page",
        raw={"data": item, "company": company_attrs},
    )


async def _get(client: httpx.AsyncClient, path: str, params: dict[str, Any]) -> httpx.Response:
    resp = await client.get(_url(path), params={k: v for k, v in params.items() if v not in (None, "", [])})
    resp.raise_for_status()
    return resp


async def subscription() -> dict:
    """GET /api_subscription. Returns {configured, used, quota, remaining, raw_status}."""
    if not configured():
        return {"configured": False}
    try:
        async with httpx.AsyncClient(headers=_headers(), timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
            data = (await _get(client, "/api_subscription", {})).json()
    except Exception as exc:  # noqa: BLE001 - surfaced as a status, never raised
        return {"configured": True, "error": safe_error(exc)}
    items = data.get("data") or []
    attrs = (items[0].get("attributes") if items and isinstance(items[0], dict) else {}) or {}
    used = attrs.get("monthly_credits_used")
    quota = attrs.get("monthly_credits_quota")
    remaining = (quota - used) if isinstance(used, (int, float)) and isinstance(quota, (int, float)) else None
    return {"configured": True, "used": used, "quota": quota, "remaining": remaining,
            "status": attrs.get("status")}


async def discover_job_openings(onet_codes: list[str], location: str, *, limit: int, max_days_old: int,
                                page: int = 1) -> SourceResult:
    """GET /discover/job_openings across all companies, filtered by O*NET code and location."""
    if not configured():
        return SourceResult(source=SOURCE, status="not_configured", message="PREDICTLEADS_API_KEY/TOKEN not set")
    if not onet_codes:
        return SourceResult(source=SOURCE, status="skipped",
                            message="PredictLeads search needs at least one O*NET code for the role")
    found_from = (utcnow() - timedelta(days=max_days_old)).strftime("%Y-%m-%d")
    params = {"onet_codes": ",".join(onet_codes), "location": location, "active_only": "true",
              "found_at_from": found_from, "limit": limit, "page": page}
    try:
        async with httpx.AsyncClient(headers=_headers(), timeout=60.0) as client:
            resp = await _get(client, "/discover/job_openings", params)
            payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        msg = "PredictLeads monthly credit limit reached (HTTP 402)" if code == 402 else safe_error(exc)
        logger.warning("predictleads discover failed: %s", msg)
        return SourceResult(source=SOURCE, status="error", message=msg,
                            usage=[UsageEvent(source=SOURCE, endpoint="discover/job_openings", status_code=code)])
    companies = _companies_index(payload)
    jobs = [j for j in (_normalize(i, companies) for i in payload.get("data") or []) if j]
    # Discovery endpoints are billed per returned result according to the pricing page.
    usage = UsageEvent(source=SOURCE, endpoint="discover/job_openings", status_code=resp.status_code,
                       credits_used=float(len(payload.get("data") or [])),
                       note="estimated: discovery billed per result")
    return SourceResult(source=SOURCE, status="ok", jobs=jobs, fetched=len(jobs), usage=[usage])


async def company_job_openings(domain: str, *, limit: int = 100) -> SourceResult:
    """GET /companies/{domain}/job_openings (1 credit per request)."""
    if not configured():
        return SourceResult(source=SOURCE, status="not_configured", message="PREDICTLEADS_API_KEY/TOKEN not set")
    dom = clean_domain(domain)
    if not dom or "." not in dom:
        return SourceResult(source=SOURCE, status="error", message="Enter a company domain such as acme.com")
    try:
        async with httpx.AsyncClient(headers=_headers(), timeout=60.0) as client:
            resp = await _get(client, f"/companies/{dom}/job_openings", {"active_only": "true", "limit": limit})
            payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        msg = {404: "Company not found in PredictLeads", 402: "PredictLeads monthly credit limit reached"}.get(
            code or 0, safe_error(exc))
        return SourceResult(source=SOURCE, status="error", message=msg,
                            usage=[UsageEvent(source=SOURCE, endpoint="companies/job_openings", status_code=code,
                                              credits_used=1 if code and code != 402 else 0)])
    companies = _companies_index(payload)
    jobs = [j for j in (_normalize(i, companies, dom) for i in payload.get("data") or []) if j]
    usage = UsageEvent(source=SOURCE, endpoint="companies/job_openings", status_code=resp.status_code, credits_used=1)
    return SourceResult(source=SOURCE, status="ok", jobs=jobs, fetched=len(jobs), usage=[usage])


async def job_opening(job_opening_id: str) -> tuple[NormalizedJob | None, UsageEvent]:
    """GET /job_openings/{id} for one full description (1 credit)."""
    try:
        async with httpx.AsyncClient(headers=_headers(), timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
            resp = await _get(client, f"/job_openings/{job_opening_id}", {})
            payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        return None, UsageEvent(source=SOURCE, endpoint="job_openings/{id}", status_code=code, note=safe_error(exc))
    data = payload.get("data")
    item = data[0] if isinstance(data, list) and data else data
    job = _normalize(item, _companies_index(payload)) if isinstance(item, dict) else None
    return job, UsageEvent(source=SOURCE, endpoint="job_openings/{id}", status_code=resp.status_code, credits_used=1)


async def request_logs(since: str) -> dict:
    """GET /api_request_logs, used once to confirm what discovery really costs."""
    if not configured():
        return {"configured": False}
    try:
        async with httpx.AsyncClient(headers=_headers(), timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
            data = (await _get(client, "/api_request_logs", {"requested_at_from": since, "limit": 100})).json()
    except Exception as exc:  # noqa: BLE001
        return {"configured": True, "error": safe_error(exc)}
    return {"configured": True, "items": [d.get("attributes") or {} for d in data.get("data") or []]}
