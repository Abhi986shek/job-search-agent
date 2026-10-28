"""Data access for job matches, job groups, CV versions and change proposals."""

from __future__ import annotations

from sqlalchemy import delete, select

from db.models import CvChangeProposal, CvVersion, Job, JobGroup, JobMatch
from db.repositories import _row
from db.session import session_scope
from utils import to_json, utcnow

# ── Matches and groups ─────────────────────────────────────────────────────────


def save_match(job_id: int, profile_id: int, score: float, gaps: list, reasons: list) -> None:
    with session_scope() as s:
        m = s.scalar(select(JobMatch).where(JobMatch.job_id == job_id, JobMatch.profile_id == profile_id))
        if not m:
            m = JobMatch(job_id=job_id, profile_id=profile_id, score=score)
            s.add(m)
        m.score = score
        m.gaps_json = to_json(gaps)
        m.reasons_json = to_json(reasons)


def replace_groups(profile_id: int, groups: list[dict]) -> list[dict]:
    """Delete this profile's groups and create new ones. groups: [{name, summary, job_ids}]."""
    with session_scope() as s:
        old_ids = list(s.scalars(select(JobGroup.id).where(JobGroup.profile_id == profile_id)).all())
        if old_ids:
            for m in s.scalars(select(JobMatch).where(JobMatch.job_group_id.in_(old_ids))).all():
                m.job_group_id = None
            s.execute(delete(JobGroup).where(JobGroup.id.in_(old_ids)))
        out = []
        for g in groups:
            row = JobGroup(name=g["name"][:200], summary=g.get("summary") or "", profile_id=profile_id)
            s.add(row)
            s.flush()
            for jid in g.get("job_ids") or []:
                m = s.scalar(select(JobMatch).where(JobMatch.job_id == jid, JobMatch.profile_id == profile_id))
                if m:
                    m.job_group_id = row.id
            out.append({**_row(row), "job_ids": g.get("job_ids") or []})
        return out


def list_matches(profile_id: int, min_score: float = 0) -> list[dict]:
    with session_scope() as s:
        stmt = (select(JobMatch, Job).join(Job, Job.id == JobMatch.job_id)
                .where(JobMatch.profile_id == profile_id, JobMatch.score >= min_score)
                .order_by(JobMatch.score.desc()))
        out = []
        for m, j in s.execute(stmt).all():
            d = _row(m, json_fields=("gaps_json", "reasons_json"))
            d["job"] = {"id": j.id, "title": j.title, "company": j.company, "location": j.location,
                        "apply_url": j.apply_url, "status": j.status}
            out.append(d)
        return out


def list_groups(profile_id: int) -> list[dict]:
    with session_scope() as s:
        groups = s.scalars(select(JobGroup).where(JobGroup.profile_id == profile_id).order_by(JobGroup.id)).all()
        out = []
        for g in groups:
            jobs = s.execute(select(Job.id, Job.title, Job.company, JobMatch.score, Job.apply_url, Job.location,
                                    Job.status)
                             .join(JobMatch, JobMatch.job_id == Job.id)
                             .where(JobMatch.job_group_id == g.id).order_by(JobMatch.score.desc())).all()
            out.append({**_row(g), "jobs": [{"id": r[0], "title": r[1], "company": r[2], "score": r[3],
                                             "apply_url": r[4], "location": r[5], "status": r[6]} for r in jobs]})
        return out


def get_group(group_id: int) -> dict | None:
    with session_scope() as s:
        g = s.get(JobGroup, group_id)
        if not g:
            return None
        jobs = s.scalars(select(Job).join(JobMatch, JobMatch.job_id == Job.id).where(JobMatch.job_group_id == g.id)).all()
        return {**_row(g), "jobs": [_row(j) for j in jobs]}


# ── CV versions ────────────────────────────────────────────────────────────────

def create_version(base_cv_id: int, job_group_id: int | None, job_id: int | None, proposals: list[dict]) -> dict:
    with session_scope() as s:
        v = CvVersion(base_cv_document_id=base_cv_id, job_group_id=job_group_id, job_id=job_id, status="draft")
        s.add(v)
        s.flush()
        for p in proposals:
            s.add(CvChangeProposal(
                cv_version_id=v.id, section=p["section"][:200], change_type=p["change_type"],
                original_text=p.get("original_text") or None, proposed_text=p.get("proposed_text") or None,
                reason=p.get("reason") or None, evidence_json=to_json(p.get("evidence") or []), status="proposed"))
        vid = v.id
    return get_version(vid)


def set_draft(version_id: int, structure: dict | None) -> bool:
    """Save the whole CV you edited in the preview, or clear it (None) to go back to the automatic version."""
    with session_scope() as s:
        v = s.get(CvVersion, version_id)
        if not v:
            return False
        v.draft_json = to_json(structure) if structure is not None else None
        if v.status == "generated":
            v.status = "draft"  # edited after generation: generate again to update the files
        return True


def get_version(version_id: int) -> dict | None:
    with session_scope() as s:
        v = s.get(CvVersion, version_id)
        if not v:
            return None
        d = _row(v, json_fields=("draft_json",))
        d["proposals"] = [_row(p, json_fields=("evidence_json",)) for p in s.scalars(
            select(CvChangeProposal).where(CvChangeProposal.cv_version_id == version_id).order_by(CvChangeProposal.id)).all()]
        if v.job_group_id:
            g = s.get(JobGroup, v.job_group_id)
            d["group_name"] = g.name if g else None
        if v.job_id:
            j = s.get(Job, v.job_id)
            d["job_title"] = f"{j.title} at {j.company}" if j else None
        return d


def list_versions() -> list[dict]:
    with session_scope() as s:
        ids = list(s.scalars(select(CvVersion.id).order_by(CvVersion.created_at.desc())).all())
    return [get_version(i) for i in ids]


def decide_proposal(proposal_id: int, status: str) -> dict | None:
    with session_scope() as s:
        p = s.get(CvChangeProposal, proposal_id)
        if not p:
            return None
        p.status = status
        p.decided_at = utcnow()
        v = s.get(CvVersion, p.cv_version_id)
        if v and v.status == "generated":
            v.status = "draft"   # decisions changed after generation: regenerate needed
        s.flush()
        return _row(p, json_fields=("evidence_json",))


def decide_all(version_id: int, status: str) -> int:
    with session_scope() as s:
        rows = s.scalars(select(CvChangeProposal).where(CvChangeProposal.cv_version_id == version_id,
                                                        CvChangeProposal.status == "proposed")).all()
        for p in rows:
            p.status = status
            p.decided_at = utcnow()
        return len(rows)


def mark_generated(version_id: int, docx_path: str, pdf_path: str) -> None:
    with session_scope() as s:
        v = s.get(CvVersion, version_id)
        if v:
            v.docx_path, v.pdf_path, v.status, v.generated_at = docx_path, pdf_path, "generated", utcnow()


def delete_version(version_id: int) -> bool:
    with session_scope() as s:
        v = s.get(CvVersion, version_id)
        if not v:
            return False
        s.delete(v)
        return True


def version_for_job(job_id: int) -> dict | None:
    """Best generated CV for a job: one made for the job itself, else for its group."""
    with session_scope() as s:
        vid = s.scalar(select(CvVersion.id).where(CvVersion.job_id == job_id, CvVersion.status == "generated")
                       .order_by(CvVersion.generated_at.desc()).limit(1))
        if not vid:
            vid = s.scalar(select(CvVersion.id).join(JobMatch, JobMatch.job_group_id == CvVersion.job_group_id)
                           .where(JobMatch.job_id == job_id, CvVersion.status == "generated")
                           .order_by(CvVersion.generated_at.desc()).limit(1))
    return get_version(vid) if vid else None
