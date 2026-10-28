"""Job discovery: run sources in parallel, normalise, dedupe, store, track usage."""

from __future__ import annotations

import asyncio

import onet
from clients import adzuna, ats_boards, freehire, predictleads, serpapi
from db import profile_repository as prepo
from db import repositories as repo
from schemas import NormalizedJob, SearchRequest, SourceResult
from utils import detect_portal, logger, normalize_text, safe_error, sha256_text

SOURCE_LABELS = {
    "predictleads": "PredictLeads (company career pages)",
    "serpapi": "SerpApi Google Jobs (includes portals)",
    "adzuna": "Adzuna India",
    "freehire": "freehire (ATS boards, aggregators, Naukri)",
    "ats": "ATS boards (Greenhouse, Lever, Ashby)",
}


_SHORT_TERMS = {"ai", "ml", "llm", "nlp", "ui", "ux", "qa", "sre"}  # short words that still matter in titles


def _keyword_filter(jobs: list[NormalizedJob], query: str) -> list[NormalizedJob]:
    stop = {"and", "the", "for", "with", "senior", "junior", "lead", "sr", "jr", "engineer", "developer"}
    words = {w for w in normalize_text(query).split() if (len(w) > 2 or w in _SHORT_TERMS) and w not in stop}
    if not words:
        return jobs
    return [j for j in jobs if words & set(normalize_text(j.title).split())]


def _store(result: SourceResult, search_id: int | None) -> dict:
    for u in result.usage:
        repo.record_usage(u.source, u.endpoint, u.credits_used, u.status_code, u.note, search_id)
    counts = {"new": 0, "merged": 0, "existing": 0}
    job_ids: list[int] = []
    for nj in result.jobs:
        try:
            jid, outcome = repo.upsert_job(nj, search_id)
            counts[outcome] += 1
            job_ids.append(jid)
        except Exception as exc:  # noqa: BLE001 - one bad record must not drop the rest
            logger.warning("store job failed (%s): %s", nj.source, safe_error(exc))
    return {"source": result.source, "status": result.status, "message": result.message,
            "fetched": result.fetched, "stored": len(job_ids), "job_ids": list(dict.fromkeys(job_ids)), **counts}


async def _ats_all(query: str) -> SourceResult:
    boards = prepo.list_ats_boards(active_only=True)
    if not boards:
        return SourceResult(source="ats", status="skipped", message="No ATS boards added yet")
    results = await asyncio.gather(*(ats_boards.fetch_board(b["provider"], b["board_token"], b["company_name"], query)
                                     for b in boards))
    for b in boards:
        prepo.touch_ats_board(b["id"])
    jobs = [j for r in results for j in r.jobs]
    errors = [r.message for r in results if r.status == "error"]
    return SourceResult(source="ats", status="ok" if jobs or not errors else "error",
                        message="; ".join(errors)[:500], jobs=jobs, fetched=len(jobs),
                        usage=[u for r in results for u in r.usage])


async def run_search(req: SearchRequest, include_ats: bool = True) -> dict:
    data = req.model_dump()
    role = repo.get_role(req.target_role_id) if req.target_role_id else None
    if role:
        data["query"] = data["query"] or role["title"]
        data["onet_codes"] = data["onet_codes"] or (role.get("onet_codes") or [])
        if not data["location"] and role.get("locations"):
            data["location"] = role["locations"][0]
    query = (data["query"] or "").strip()
    if not query:
        raise ValueError("Enter a search query or pick a target role")
    if not data["onet_codes"]:
        data["onet_codes"] = [s["code"] for s in onet.suggest(query, limit=2)]

    search_id = repo.create_search(data)
    limit = data["limit_per_source"]
    tasks = {}
    if "predictleads" in data["sources"]:
        tasks["predictleads"] = predictleads.discover_job_openings(
            data["onet_codes"], data["country"], limit=min(limit, max(1, _pl_limit())),
            max_days_old=data["max_days_old"])
    if "serpapi" in data["sources"]:
        tasks["serpapi"] = serpapi.search(query, data["location"], limit=limit)
    if "adzuna" in data["sources"]:
        tasks["adzuna"] = adzuna.search(query, data["location"], limit=limit, max_days_old=data["max_days_old"])
    if "freehire" in data["sources"]:
        tasks["freehire"] = freehire.search(query, data["location"], limit=limit, max_days_old=data["max_days_old"])
    if include_ats:
        tasks["ats"] = _ats_all(query)

    raw = await asyncio.gather(*tasks.values(), return_exceptions=True)
    summary = []
    for name, res in zip(tasks.keys(), raw):
        if isinstance(res, BaseException):
            res = SourceResult(source=name, status="error", message=safe_error(res))
        if name == "predictleads" and res.status == "ok" and data["keyword_filter_predictleads"]:
            before = len(res.jobs)
            res.jobs = _keyword_filter(res.jobs, query)
            res.message = f"kept {len(res.jobs)} of {before} after title keyword filter"
        entry = _store(res, search_id)
        entry["label"] = SOURCE_LABELS.get(name, name)
        summary.append(entry)

    ok = any(s["status"] == "ok" for s in summary)
    repo.finish_search(search_id, {"sources": summary, "onet_codes": data["onet_codes"]},
                       "completed" if ok else "failed")
    return {"search_id": search_id, "query": query, "onet_codes": data["onet_codes"], "sources": summary,
            "jobs": repo.list_jobs(search_id=search_id, limit=500)["items"]}


def _pl_limit() -> int:
    from config import settings
    return settings.PREDICTLEADS_DISCOVER_LIMIT


async def company_jobs(domain: str, limit: int) -> dict:
    res = await predictleads.company_job_openings(domain, limit=limit)
    entry = _store(res, None)
    jobs = [repo.get_job(jid) for jid in entry["job_ids"]]
    for j in jobs:
        for src in j.get("sources") or []:
            src.pop("raw", None)
    return {"summary": entry, "jobs": jobs}


async def ats_board_jobs(board_id: int) -> dict:
    board = next((b for b in prepo.list_ats_boards() if b["id"] == board_id), None)
    if not board:
        raise LookupError("ATS board not found")
    res = await ats_boards.fetch_board(board["provider"], board["board_token"], board["company_name"])
    prepo.touch_ats_board(board_id)
    return _store(res, None)


async def predictleads_job_details(job_id: int) -> dict:
    job = repo.get_job(job_id)
    if not job:
        raise LookupError("Job not found")
    record_id = repo.predictleads_record_id(job_id)
    if not record_id:
        raise ValueError("This job did not come from PredictLeads")
    nj, usage = await predictleads.job_opening(record_id)
    repo.record_usage(usage.source, usage.endpoint, usage.credits_used, usage.status_code, usage.note)
    if nj and nj.description:
        repo.set_job_description(job_id, nj.description)
    return repo.get_job(job_id)


def add_guidance_urls(items: list[dict]) -> list[dict]:
    """Store job links you found yourself. The page is never fetched; only your text is used."""
    out = []
    for item in items:
        url = item["url"].strip()
        portal = detect_portal(url)
        row, created = repo.add_guidance_url(item, portal)
        title = item.get("title") or f"Job link from {portal}"
        nj = NormalizedJob(source="guidance", source_job_id="guidance:" + sha256_text(url), title=title,
                           company=item.get("company") or "", location=item.get("location") or "",
                           description=item.get("pasted_description") or "", apply_url=url, source_url=url,
                           via=portal, raw={"note": item.get("note") or ""})
        job_id, _ = repo.upsert_job(nj, None)
        repo.link_guidance_job(row["id"], job_id)
        out.append({**row, "job_id": job_id, "created": created})
    return out


async def source_status() -> dict:
    from config import settings

    pl, sa = await asyncio.gather(predictleads.subscription(), serpapi.account())
    return {
        "predictleads": {"label": SOURCE_LABELS["predictleads"], **pl},
        "serpapi": {"label": SOURCE_LABELS["serpapi"], **sa},
        "adzuna": {"label": SOURCE_LABELS["adzuna"], "configured": settings.adzuna_configured,
                   "country": settings.ADZUNA_COUNTRY},
        "freehire": {"label": SOURCE_LABELS["freehire"], "configured": True, "country": settings.FREEHIRE_COUNTRY},
        "ats": {"label": SOURCE_LABELS["ats"], "configured": True, "boards": len(prepo.list_ats_boards(True))},
        "bedrock": {"configured": settings.bedrock_configured, "model_id": settings.BEDROCK_MODEL_ID or None},
        "apollo": {"configured": bool(settings.APOLLO_API_KEY)},
        "apify": {"configured": bool(settings.APIFY_TOKEN)},
        "github_personal": {"configured": bool(settings.GITHUB_PERSONAL_TOKEN or settings.GITHUB_PERSONAL_USERNAME)},
        "github_company": {"configured": bool(settings.GITHUB_COMPANY_ORG)},
        "gmail_oauth_client": {"configured": bool(settings.GMAIL_OAUTH_CLIENT_FILE)},
        "smtp": {"configured": bool(settings.SMTP_USERNAME and settings.SMTP_APP_PASSWORD)},
        "encryption_key": {"configured": bool(settings.ENCRYPTION_KEY)},
    }
