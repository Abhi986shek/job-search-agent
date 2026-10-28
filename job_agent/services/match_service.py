"""Score jobs against the current profile, then group jobs with similar requirements."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

import llm
from db import cv_repository as crepo
from db import profile_repository as prepo
from db import repositories as repo
from services.profile_service import _run_llm
from utils import to_json


class Gap(BaseModel):
    gap: str
    reason: str = ""
    severity: str = Field(default="medium", description="low | medium | high")


class JobScore(BaseModel):
    job_id: int
    score: int = Field(ge=0, le=100)
    matched_skills: list[str] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class JobScores(BaseModel):
    scores: list[JobScore]


class Group(BaseModel):
    name: str = Field(description="Short label, e.g. 'Python backend' or 'Data engineering'")
    summary: str = ""
    job_ids: list[int]


class Groups(BaseModel):
    groups: list[Group]


SCORE_SYSTEM = (
    "You compare job postings with a candidate profile. Score 0-100 for fit: skills, experience level, domain and "
    "location. List concrete gaps with a reason each. Be honest: missing must-have skills lower the score.\n"
    "Experience rules (always apply, using the candidate's experience given in the prompt):\n"
    "- Compare the years the job asks for with the candidate's total years of experience.\n"
    "- If the job asks for more years than the candidate has, add a gap with severity high that states the years "
    "asked, and lower the score by at least 25 points.\n"
    "- If the job's seniority (senior, lead, staff, principal, manager, head) is above the candidate's current "
    "level, add a high-severity gap and lower the score accordingly.\n"
    "- Jobs asking for no more years than the candidate has, or stating no requirement, are not penalised for "
    "experience. Never reward extra years beyond the requirement.\n"
    "- Say in the reasons which experience fact you used, e.g. 'Asks 5+ years; candidate has 2'.\n"
    + llm.FACTS_RULE
)

_YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:\+\s*)?years?", re.I)
_SENIORITY_RE = re.compile(r"\b(intern|junior|middle|senior|lead|staff|principal|head|director|manager)\b", re.I)


def _experience_asked(j: dict) -> str:
    """Years and seniority the job asks for: the source's own enrichment when present, else the text."""
    years, seniority = None, ""
    for src in j.get("sources") or []:
        raw = src.get("raw") or {}
        enr = raw.get("enrichment") or {}
        if enr.get("experience_years_min") is not None and years is None:
            years = enr.get("experience_years_min")
        if enr.get("seniority") and not seniority:
            seniority = enr["seniority"]
    text = f"{j.get('title') or ''} {(j.get('description') or '')[:3000]}"
    if years is None:
        found = [int(m.group(1)) for m in _YEARS_RE.finditer(text) if int(m.group(1)) <= 30]
        if found:
            years = min(found)
    if not seniority:
        m = _SENIORITY_RE.search(j.get("title") or "")
        if m:
            seniority = m.group(1).lower()
    years_txt = f"{years}+ years" if years is not None else "not stated"
    return f"Experience asked: {years_txt}; seniority: {seniority or 'not stated'}"


def _candidate_experience(profile: dict) -> str:
    p = profile or {}
    roles = "; ".join(f"{e.get('title')} at {e.get('company') or 'unknown company'} "
                      f"({e.get('start') or '?'} to {e.get('end') or '?'})" for e in p.get("experience") or [])
    return (f"Candidate experience: total {p.get('total_years_experience') if p.get('total_years_experience') is not None else 'not stated'} "
            f"years; current title: {p.get('current_title') or 'not stated'}; roles: {roles or 'none stated'}")


def _job_brief(j: dict, desc_chars: int = 2500) -> str:
    return (f"job_id={j['id']}\nTitle: {j['title']}\nCompany: {j.get('company')}\nLocation: {j.get('location')}\n"
            f"{_experience_asked(j)}\n"
            f"Description: {(j.get('description') or '')[:desc_chars]}")


async def match_jobs(job_ids: list[int] | None = None, status: str | None = None, limit: int = 40,
                     regroup: bool = True) -> dict:
    profile = prepo.get_current_profile()
    if not profile:
        raise ValueError("Build your profile first")
    remaining = 0
    if job_ids:
        jobs = [j for j in (repo.get_job(i) for i in job_ids) if j]
    else:
        # Every open job that has no score for this profile yet, newest first. Each run scores the next batch,
        # so older jobs are reached too. Rejected and archived jobs are skipped.
        open_jobs = [j for j in repo.list_jobs(status=status, limit=1000)["items"]
                     if j["status"] not in ("rejected", "archived")]
        if not open_jobs:
            raise ValueError("No jobs to match. Run a search first.")
        scored_ids = {m["job_id"] for m in crepo.list_matches(profile["id"])}
        pending = [j for j in open_jobs if j["id"] not in scored_ids]
        jobs = pending[:limit]
        remaining = len(pending) - len(jobs)
        if not jobs:
            groups = await group_jobs() if regroup else []
            return {"profile_id": profile["id"], "scored": 0, "remaining": 0, "groups": groups,
                    "matches": crepo.list_matches(profile["id"])}
    if not jobs:
        raise ValueError("No jobs to match. Run a search first.")
    profile_text = to_json(profile["profile"])
    experience_text = _candidate_experience(profile["profile"])
    valid_ids = {j["id"] for j in jobs}
    scored = 0
    for i in range(0, len(jobs), 8):
        batch = [repo.get_job(j["id"]) or j for j in jobs[i:i + 8]]  # full job, with source enrichment
        result = await _run_llm(JobScores, SCORE_SYSTEM,
                                f"{experience_text}\n\nCandidate profile:\n{profile_text}\n\nJobs:\n\n"
                                + "\n\n---\n\n".join(_job_brief(j) for j in batch))
        for s in result.scores:
            if s.job_id in valid_ids:
                crepo.save_match(s.job_id, profile["id"], s.score, [g.model_dump() for g in s.gaps],
                                 s.reasons + ([f"Matched skills: {', '.join(s.matched_skills)}"] if s.matched_skills else []))
                scored += 1
    groups = await group_jobs() if regroup else []
    return {"profile_id": profile["id"], "scored": scored, "remaining": remaining, "groups": groups,
            "matches": crepo.list_matches(profile["id"])}


async def group_jobs(min_score: float = 0) -> list[dict]:
    profile = prepo.get_current_profile()
    if not profile:
        raise ValueError("Build your profile first")
    matches = crepo.list_matches(profile["id"], min_score=min_score)
    if not matches:
        return []
    lines = []
    for m in matches[:150]:
        j = repo.get_job(m["job_id"])
        lines.append(f"job_id={m['job_id']} | {j['title']} | {j.get('company')} | "
                     f"{(j.get('description') or '')[:400]}")
    result = await _run_llm(
        Groups,
        "Group these jobs so that one tailored CV can serve every job in a group. Jobs needing different emphasis "
        "(different core stack or role type) go in different groups. Use 1 to 6 groups. Every job_id appears exactly once.",
        "\n".join(lines))
    valid = {m["job_id"] for m in matches[:150]}
    seen: set[int] = set()
    groups = []
    for g in result.groups:
        ids = [i for i in g.job_ids if i in valid and i not in seen]
        seen.update(ids)
        if ids:
            groups.append({"name": g.name, "summary": g.summary, "job_ids": ids})
    leftovers = sorted(valid - seen)
    if leftovers:
        groups.append({"name": "Other", "summary": "Jobs not placed in a group", "job_ids": leftovers})
    return crepo.replace_groups(profile["id"], groups)
