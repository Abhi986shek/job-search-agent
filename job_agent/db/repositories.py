"""All data access. Functions return plain dicts, never ORM objects."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from collections import defaultdict

from sqlalchemy import func, or_, select, update

from db.models import (
    ApiUsage,
    AuditLog,
    CvVersion,
    GuidanceUrl,
    Job,
    JobContact,
    JobMatch,
    JobRef,
    JobSearch,
    JobSourceRecord,
    OutreachThread,
    TargetRole,
)
from db.session import session_scope
from schemas import NormalizedJob
from utils import (
    apply_url_rank,
    cities_in,
    from_json,
    job_match_refs,
    make_dedupe_key,
    normalize_company,
    normalize_title,
    primary_city,
    same_company,
    sha256_text,
    title_similarity,
    to_json,
    utcnow,
)


def _row(obj: Any, *, json_fields: tuple[str, ...] = ()) -> dict:
    out = {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
    for f in json_fields:
        key = f.removesuffix("_json")
        out[key] = from_json(out.pop(f), default=None)
    return out


# ── Audit and usage ────────────────────────────────────────────────────────────

def add_audit(action: str, entity_type: str, entity_id: int | None, details: dict | None = None) -> None:
    with session_scope() as s:
        s.add(AuditLog(action=action, entity_type=entity_type, entity_id=entity_id,
                       details_json=to_json(details or {})))


def record_usage(source: str, endpoint: str, credits_used: float, status_code: int | None,
                 note: str = "", job_search_id: int | None = None) -> None:
    with session_scope() as s:
        s.add(ApiUsage(source=source, endpoint=endpoint, credits_used=credits_used,
                       status_code=status_code, note=note[:500], job_search_id=job_search_id))


def usage_summary(days: int = 30) -> dict:
    since = utcnow() - timedelta(days=days)
    with session_scope() as s:
        rows = s.execute(
            select(ApiUsage.source, func.count(ApiUsage.id), func.coalesce(func.sum(ApiUsage.credits_used), 0))
            .where(ApiUsage.called_at >= since)
            .group_by(ApiUsage.source)
        ).all()
        recent = s.scalars(select(ApiUsage).order_by(ApiUsage.called_at.desc()).limit(100)).all()
        return {
            "days": days,
            "totals": [{"source": r[0], "calls": r[1], "credits": float(r[2])} for r in rows],
            "recent": [_row(u) for u in recent],
        }


# ── Target roles ───────────────────────────────────────────────────────────────

_ROLE_JSON = ("locations_json", "onet_codes_json")


def create_role(data: dict) -> dict:
    with session_scope() as s:
        role = TargetRole(
            title=data["title"].strip(),
            seniority=data.get("seniority") or None,
            locations_json=to_json(data.get("locations") or []),
            remote_ok=bool(data.get("remote_ok")),
            onet_codes_json=to_json(data.get("onet_codes") or []),
            status=data.get("status") or "confirmed",
        )
        s.add(role)
        s.flush()
        return _row(role, json_fields=_ROLE_JSON)


def list_roles(status: str | None = None) -> list[dict]:
    with session_scope() as s:
        q = select(TargetRole).order_by(TargetRole.created_at.desc())
        if status:
            q = q.where(TargetRole.status == status)
        return [_row(r, json_fields=_ROLE_JSON) for r in s.scalars(q).all()]


def get_role(role_id: int) -> dict | None:
    with session_scope() as s:
        role = s.get(TargetRole, role_id)
        return _row(role, json_fields=_ROLE_JSON) if role else None


def update_role(role_id: int, data: dict) -> dict | None:
    with session_scope() as s:
        role = s.get(TargetRole, role_id)
        if not role:
            return None
        for key in ("title", "seniority", "remote_ok", "status"):
            if data.get(key) is not None:
                setattr(role, key, data[key])
        if data.get("locations") is not None:
            role.locations_json = to_json(data["locations"])
        if data.get("onet_codes") is not None:
            role.onet_codes_json = to_json(data["onet_codes"])
        s.flush()
        return _row(role, json_fields=_ROLE_JSON)


def delete_role(role_id: int) -> bool:
    with session_scope() as s:
        role = s.get(TargetRole, role_id)
        if not role:
            return False
        s.delete(role)
        return True


# ── Searches ───────────────────────────────────────────────────────────────────

_SEARCH_JSON = ("sources_json", "request_json", "results_summary_json")


def create_search(request: dict) -> int:
    with session_scope() as s:
        search = JobSearch(
            target_role_id=request.get("target_role_id"),
            query=request.get("query") or "",
            location=request.get("location") or None,
            country=request.get("country") or None,
            sources_json=to_json(request.get("sources") or []),
            request_json=to_json(request),
            status="running",
        )
        s.add(search)
        s.flush()
        return search.id


def finish_search(search_id: int, summary: dict, status: str) -> None:
    with session_scope() as s:
        search = s.get(JobSearch, search_id)
        if search:
            search.results_summary_json = to_json(summary)
            search.status = status
            search.finished_at = utcnow()


def list_searches(limit: int = 50) -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(select(JobSearch).order_by(JobSearch.started_at.desc()).limit(limit)).all()
        return [_row(r, json_fields=_SEARCH_JSON) for r in rows]


def get_search(search_id: int) -> dict | None:
    with session_scope() as s:
        row = s.get(JobSearch, search_id)
        return _row(row, json_fields=_SEARCH_JSON) if row else None


# ── Jobs ───────────────────────────────────────────────────────────────────────

def _fill_missing(job: Job, nj: NormalizedJob) -> None:
    """Keep the first value seen; fill only empty fields. A longer description wins, and a
    company or ATS apply link replaces a portal or aggregator link."""
    for attr in ("company_domain", "location", "posted_text", "salary_text", "employment_type"):
        if not getattr(job, attr) and getattr(nj, attr):
            setattr(job, attr, getattr(nj, attr))
    if nj.apply_url and apply_url_rank(nj.apply_url) < apply_url_rank(job.apply_url):
        job.apply_url = nj.apply_url[:2000]
    if not job.posted_at and nj.posted_at:
        job.posted_at = nj.posted_at
    if nj.description and len(nj.description) > len(job.description or ""):
        job.description = nj.description


def _dedupe_key_for(company: str | None, title: str | None, location: str | None, fallback: str) -> str:
    key = make_dedupe_key(company, title, location)
    if key.startswith("|"):  # no company: fall back to the URL so unrelated jobs never merge
        key = "url:" + sha256_text(fallback)
    return key[:800]


def _find_existing_job(s, nj: NormalizedJob, key: str, refs: list[str]) -> Job | None:
    """Shared ref first, then the exact key, then same company+title with a city in common."""
    if refs:
        job_id = s.scalar(select(JobRef.job_id).where(JobRef.ref.in_(refs)).limit(1))
        job = s.get(Job, job_id) if job_id else None
        if job:
            return job
    job = s.scalar(select(Job).where(Job.dedupe_key == key))
    if job or key.startswith("url:"):
        return job
    company, title, _ = key.split("|", 2)
    new_cities = set(cities_in(nj.location))
    if not (company and title and new_cities):
        return None
    for cand in s.scalars(select(Job).where(Job.dedupe_key.startswith(f"{company}|{title}|", autoescape=True))):
        if new_cities & set(cities_in(cand.location)):
            return cand
    return None


def _attach_refs(s, job_id: int, refs: list[str]) -> None:
    for ref in refs:
        if not s.scalar(select(JobRef.id).where(JobRef.ref == ref)):
            s.add(JobRef(job_id=job_id, ref=ref))
            s.flush()


def upsert_job(nj: NormalizedJob, job_search_id: int | None) -> tuple[int, str]:
    """Insert or merge one normalised job. Returns (job_id, outcome).

    outcome is 'new' (new job), 'merged' (new source for a known job), or
    'existing' (this exact source record was already stored).
    """
    refs = job_match_refs(nj.source, nj.source_job_id, nj.apply_url, nj.source_url)
    with session_scope() as s:
        record = s.scalar(select(JobSourceRecord).where(
            JobSourceRecord.source == nj.source, JobSourceRecord.source_job_id == nj.source_job_id))
        if record:
            job = s.get(Job, record.job_id)
            if job:
                _fill_missing(job, nj)
                _attach_refs(s, job.id, refs)
            record.raw_json = to_json(nj.raw)
            record.fetched_at = utcnow()
            return record.job_id, "existing"

        key = _dedupe_key_for(nj.company, nj.title, nj.location,
                              nj.apply_url or nj.source_url or f"{nj.source}:{nj.source_job_id}")
        job = _find_existing_job(s, nj, key, refs)
        outcome = "merged"
        if not job:
            job = Job(
                title=nj.title[:300], company=nj.company[:300] or None, company_domain=nj.company_domain or None,
                location=nj.location[:300] or None, description=nj.description or None, posted_at=nj.posted_at,
                posted_text=nj.posted_text[:100] or None, apply_url=nj.apply_url[:2000] or None,
                salary_text=nj.salary_text[:200] or None, employment_type=nj.employment_type[:100] or None,
                dedupe_key=key[:800], status="new",
            )
            s.add(job)
            s.flush()
            outcome = "new"
        else:
            _fill_missing(job, nj)

        s.add(JobSourceRecord(
            job_id=job.id, job_search_id=job_search_id, source=nj.source, source_job_id=nj.source_job_id[:500],
            source_url=(nj.source_url or nj.apply_url)[:2000] or None, via=nj.via[:200] or None,
            raw_json=to_json(nj.raw),
        ))
        s.flush()
        _attach_refs(s, job.id, refs)
        return job.id, outcome


# ── Duplicates: merge, review, re-key ──────────────────────────────────────────

def _merge_into(s, keep: Job, drop: Job) -> None:
    """Move everything from `drop` to `keep`, then delete `drop`. Caller owns the session."""
    for model, other in ((JobMatch, JobMatch.profile_id), (JobContact, JobContact.contact_id)):
        taken = set(s.scalars(select(other).where(model.job_id == keep.id)).all())
        for row in s.scalars(select(model).where(model.job_id == drop.id)).all():
            if getattr(row, other.key) in taken:
                s.delete(row)  # keep already has this match/contact
            else:
                row.job_id = keep.id
    s.flush()
    for model in (JobSourceRecord, JobRef, GuidanceUrl, CvVersion, OutreachThread):
        s.execute(update(model).where(model.job_id == drop.id).values(job_id=keep.id))
    for attr in ("company", "company_domain", "location", "posted_text", "salary_text", "employment_type",
                 "posted_at"):
        if not getattr(keep, attr) and getattr(drop, attr):
            setattr(keep, attr, getattr(drop, attr))
    if len(drop.description or "") > len(keep.description or ""):
        keep.description = drop.description
    if drop.apply_url and apply_url_rank(drop.apply_url) < apply_url_rank(keep.apply_url):
        keep.apply_url = drop.apply_url
    if keep.status == "new" and drop.status != "new":
        keep.status = drop.status
    s.flush()
    s.delete(drop)
    s.flush()


def merge_jobs(keep_id: int, drop_id: int) -> dict | None:
    """Merge job `drop_id` into `keep_id` (sources, matches, CVs, contacts, outreach move over)."""
    if keep_id == drop_id:
        raise ValueError("Pick two different jobs to merge")
    with session_scope() as s:
        keep, drop = s.get(Job, keep_id), s.get(Job, drop_id)
        if not keep or not drop:
            return None
        _merge_into(s, keep, drop)
        result = _job_dict(s, keep)
    add_audit("job_merge", "job", keep_id, {"merged_job_id": drop_id})
    return result


def mark_not_duplicate(job_a: int, job_b: int) -> None:
    add_audit("job_not_duplicate", "job", min(job_a, job_b), {"a": min(job_a, job_b), "b": max(job_a, job_b)})


def possible_duplicates(threshold: float = 0.75, limit: int = 100) -> list[dict]:
    """Pairs that may be the same posting but were not merged automatically: same company
    (or one name extends the other), similar titles, and a city in common or no city on one side."""
    with session_scope() as s:
        dismissed = {(d.get("a"), d.get("b")) for d in
                     (from_json(x, {}) for x in s.scalars(select(AuditLog.details_json)
                                                          .where(AuditLog.action == "job_not_duplicate")).all())}
        sources: dict[int, set[str]] = defaultdict(set)
        for job_id, source in s.execute(select(JobSourceRecord.job_id, JobSourceRecord.source)).all():
            sources[job_id].add(source)
        groups: dict[str, list[dict]] = defaultdict(list)
        for j in s.scalars(select(Job).where(Job.status != "archived")).all():
            company = normalize_company(j.company)
            if not company:
                continue
            cities = set(cities_in(j.location)) or ({primary_city(j.location)} - {""})
            groups[company.split()[0]].append({
                "id": j.id, "title": j.title, "company": j.company, "location": j.location, "status": j.status,
                "source_names": sorted(sources[j.id]), "_company": company, "_title": normalize_title(j.title),
                "_cities": cities})
        pairs = []
        for items in groups.values():
            for i, a in enumerate(items):
                for b in items[i + 1:]:
                    if (min(a["id"], b["id"]), max(a["id"], b["id"])) in dismissed:
                        continue
                    if not same_company(a["_company"], b["_company"]):
                        continue
                    if a["_cities"] and b["_cities"] and not (a["_cities"] & b["_cities"]):
                        continue
                    sim = title_similarity(a["_title"], b["_title"])
                    if sim < threshold:
                        continue
                    first, second = sorted((a, b), key=lambda x: x["id"])
                    pairs.append({"job_a": {k: v for k, v in first.items() if not k.startswith("_")},
                                  "job_b": {k: v for k, v in second.items() if not k.startswith("_")},
                                  "similarity": sim})
        pairs.sort(key=lambda p: p["similarity"], reverse=True)
        return pairs[:limit]


def rededupe_all(apply: bool = False) -> dict:
    """Re-apply the current dedupe rules to every stored job (no API calls).

    Recomputes keys and refs from stored data and merges jobs the rules now say are the same
    posting, keeping the oldest job. With apply=False nothing is written."""
    with session_scope() as s:
        jobs = s.scalars(select(Job).order_by(Job.id)).all()
        refs_by_job: dict[int, set[str]] = defaultdict(set)
        for r in s.scalars(select(JobSourceRecord)).all():
            refs_by_job[r.job_id].update(job_match_refs(r.source, r.source_job_id, r.source_url))
        parent = {j.id: j.id for j in jobs}

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)

        keys: dict[int, str] = {}
        owner_ref: dict[str, int] = {}
        owner_key: dict[str, int] = {}
        by_company_title: dict[tuple[str, str], list[tuple[int, set[str]]]] = defaultdict(list)
        for j in jobs:
            refs_by_job[j.id].update(job_match_refs("", "", j.apply_url))
            key = (j.dedupe_key if j.dedupe_key.startswith("url:") and not normalize_company(j.company)
                   else _dedupe_key_for(j.company, j.title, j.location, j.apply_url or f"job:{j.id}"))
            keys[j.id] = key
            for ref in refs_by_job[j.id]:
                if ref in owner_ref:
                    union(owner_ref[ref], j.id)
                else:
                    owner_ref[ref] = j.id
            if key in owner_key:
                union(owner_key[key], j.id)
            else:
                owner_key[key] = j.id
            if not key.startswith("url:"):
                company, title, _ = key.split("|", 2)
                cities = set(cities_in(j.location))
                for other_id, other_cities in by_company_title[(company, title)]:
                    if cities & other_cities:
                        union(other_id, j.id)
                by_company_title[(company, title)].append((j.id, cities))

        members: dict[int, list[int]] = defaultdict(list)
        for j in jobs:
            members[find(j.id)].append(j.id)
        merges = [{"keep": root, "merge": [x for x in ids if x != root]} for root, ids in members.items() if len(ids) > 1]
        report = {
            "jobs": len(jobs),
            "groups_to_merge": len(merges),
            "jobs_removed": sum(len(m["merge"]) for m in merges),
            "keys_changed": sum(1 for j in jobs if find(j.id) == j.id and keys[j.id] != j.dedupe_key),
            "merges": merges[:200],
            "applied": apply,
        }
        if not apply:
            return report

        by_id = {j.id: j for j in jobs}
        for m in merges:
            for drop_id in m["merge"]:
                _merge_into(s, by_id[m["keep"]], by_id[drop_id])
        survivors = [by_id[root] for root in members]
        for j in survivors:  # two passes so the unique key never collides mid-update
            j.dedupe_key = f"tmp:{j.id}"
        s.flush()
        for j in survivors:
            j.dedupe_key = keys[j.id]
        s.flush()
        existing = set(s.scalars(select(JobRef.ref)).all())
        for root, ids in members.items():
            for job_id in ids:
                for ref in refs_by_job[job_id]:
                    if ref not in existing:
                        s.add(JobRef(job_id=root, ref=ref))
                        existing.add(ref)
    add_audit("jobs_rededupe", "job", None, {k: v for k, v in report.items() if k != "merges"})
    return report


def _job_dict(s, job: Job, *, with_raw: bool = False) -> dict:
    out = _row(job)
    records = s.scalars(select(JobSourceRecord).where(JobSourceRecord.job_id == job.id)
                        .order_by(JobSourceRecord.fetched_at)).all()
    out["sources"] = [
        {
            "id": r.id, "source": r.source, "source_job_id": r.source_job_id, "source_url": r.source_url,
            "via": r.via, "fetched_at": r.fetched_at, "job_search_id": r.job_search_id,
            **({"raw": from_json(r.raw_json, {})} if with_raw else {}),
        }
        for r in records
    ]
    out["source_names"] = sorted({r.source for r in records})
    out["via"] = sorted({r.via for r in records if r.via})
    return out


def list_jobs(*, status: str | None = None, source: str | None = None, q: str | None = None,
              search_id: int | None = None, limit: int = 200, offset: int = 0) -> dict:
    with session_scope() as s:
        stmt = select(Job)
        if status:
            stmt = stmt.where(Job.status == status)
        if source or search_id:
            sub = select(JobSourceRecord.job_id)
            if source:
                sub = sub.where(JobSourceRecord.source == source)
            if search_id:
                sub = sub.where(JobSourceRecord.job_search_id == search_id)
            stmt = stmt.where(Job.id.in_(sub))
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(or_(Job.title.ilike(like), Job.company.ilike(like), Job.location.ilike(like)))
        total = s.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = s.scalars(stmt.order_by(Job.created_at.desc()).limit(limit).offset(offset)).all()
        return {"total": total or 0, "items": [_job_dict(s, j) for j in rows]}


def get_job(job_id: int) -> dict | None:
    with session_scope() as s:
        job = s.get(Job, job_id)
        return _job_dict(s, job, with_raw=True) if job else None


def update_job_status(job_id: int, status: str) -> dict | None:
    with session_scope() as s:
        job = s.get(Job, job_id)
        if not job:
            return None
        job.status = status
        s.flush()
        return _job_dict(s, job)


def set_job_description(job_id: int, description: str) -> None:
    with session_scope() as s:
        job = s.get(Job, job_id)
        if job and description and len(description) > len(job.description or ""):
            job.description = description


def predictleads_record_id(job_id: int) -> str | None:
    with session_scope() as s:
        return s.scalar(select(JobSourceRecord.source_job_id).where(
            JobSourceRecord.job_id == job_id, JobSourceRecord.source == "predictleads").limit(1))


# ── Guidance URLs ──────────────────────────────────────────────────────────────

def add_guidance_url(data: dict, portal: str) -> tuple[dict, bool]:
    """Store a guidance URL and link it to a job. Returns (row, created)."""
    url = data["url"].strip()
    with session_scope() as s:
        existing = s.scalar(select(GuidanceUrl).where(GuidanceUrl.url == url))
        if existing:
            for key in ("title", "company", "location", "pasted_description", "note"):
                if data.get(key):
                    setattr(existing, key, data[key])
            s.flush()
            return _row(existing), False
        row = GuidanceUrl(url=url, portal=portal, title=data.get("title") or None,
                          company=data.get("company") or None, location=data.get("location") or None,
                          pasted_description=data.get("pasted_description") or None, note=data.get("note") or None)
        s.add(row)
        s.flush()
        return _row(row), True


def link_guidance_job(guidance_id: int, job_id: int) -> None:
    with session_scope() as s:
        row = s.get(GuidanceUrl, guidance_id)
        if row:
            row.job_id = job_id


def list_guidance_urls() -> list[dict]:
    with session_scope() as s:
        return [_row(r) for r in s.scalars(select(GuidanceUrl).order_by(GuidanceUrl.created_at.desc())).all()]


def delete_guidance_url(guidance_id: int) -> bool:
    """Remove the guidance entry and its source record. The job stays if other sources found it."""
    with session_scope() as s:
        row = s.get(GuidanceUrl, guidance_id)
        if not row:
            return False
        job_id = row.job_id
        record_id = "guidance:" + sha256_text(row.url)
        s.delete(row)
        rec = s.scalar(select(JobSourceRecord).where(
            JobSourceRecord.source == "guidance", JobSourceRecord.source_job_id == record_id))
        if rec:
            s.delete(rec)
            s.flush()
        if job_id:
            others = s.scalar(select(func.count(JobSourceRecord.id)).where(JobSourceRecord.job_id == job_id))
            if not others:
                job = s.get(Job, job_id)
                if job:
                    s.delete(job)
        return True


def last_search_time(source: str) -> datetime | None:
    with session_scope() as s:
        return s.scalar(select(func.max(ApiUsage.called_at)).where(ApiUsage.source == source))


# ── Assistant chat history ─────────────────────────────────────────────────────

def add_assistant_message(session_id: str, role: str, content: str, tools: list[str] | None = None) -> None:
    from db.models import AssistantMessage

    with session_scope() as s:
        s.add(AssistantMessage(session_id=session_id, role=role, content=content[:20000],
                               tools_json=to_json(tools) if tools else None))


def list_assistant_messages(session_id: str) -> list[dict]:
    from db.models import AssistantMessage

    with session_scope() as s:
        rows = s.scalars(select(AssistantMessage).where(AssistantMessage.session_id == session_id)
                         .order_by(AssistantMessage.id)).all()
        return [{"role": r.role, "content": r.content, "tools": from_json(r.tools_json, None)} for r in rows]


def list_assistant_sessions(limit: int = 30) -> list[dict]:
    """Past conversations, newest first, each with its first user message as the title."""
    from db.models import AssistantMessage

    with session_scope() as s:
        rows = s.scalars(select(AssistantMessage).order_by(AssistantMessage.id)).all()
    sessions: dict[str, dict] = {}
    for r in rows:
        item = sessions.setdefault(r.session_id, {"session_id": r.session_id, "title": "", "messages": 0,
                                                  "last_at": r.created_at})
        item["messages"] += 1
        item["last_at"] = r.created_at
        if not item["title"] and r.role == "user":
            item["title"] = r.content[:80]
    ordered = sorted(sessions.values(), key=lambda x: x["last_at"], reverse=True)
    for item in ordered:
        item["last_at"] = item["last_at"].isoformat(timespec="minutes")
    return ordered[:limit]
