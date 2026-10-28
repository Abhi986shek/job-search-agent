"""CV tailoring: structure the base CV, propose changes per job group (or job), apply only approved
changes, and render DOCX + PDF. The uploaded CV file is never modified."""

from __future__ import annotations

import copy
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

import llm
from config import OUTPUTS_DIR
from db import cv_repository as crepo
from db import profile_repository as prepo
from db import repositories as repo
import cv_render
from services.profile_service import _run_llm
from utils import normalize_text, slugify, to_json

# ── CV structure ───────────────────────────────────────────────────────────────


class CvItem(BaseModel):
    heading: str = Field(default="", description="Employer, project or institution")
    subheading: str = Field(default="", description="Job title, degree, or role")
    dates: str = ""
    bullets: list[str] = Field(default_factory=list)


class CvSection(BaseModel):
    title: str
    items: list[CvItem] = Field(default_factory=list)


class CvStructure(BaseModel):
    name: str = ""
    headline: str = ""
    contact: list[str] = Field(default_factory=list)
    sections: list[CvSection] = Field(default_factory=list)


def current_structure() -> dict:
    """The CV content: the current approved profile, laid out in CV sections. No LLM, nothing invented."""
    profile = prepo.get_current_profile()
    if not profile:
        raise ValueError("Build your profile first")
    return cv_render.structure_from_profile(profile["profile"], cv_render.load_extras())


async def ensure_structure(cv_id: int, force: bool = False) -> dict:
    cv = prepo.get_cv(cv_id)
    if not cv:
        raise LookupError("CV not found")
    if cv.get("structure") and not force:
        return cv["structure"]
    result = await _run_llm(
        CvStructure,
        "Convert this CV text into structured sections. Copy every bullet verbatim; do not rewrite, merge or drop "
        "anything. Skills go in a section titled 'Skills' with one bullet per skill line. " + llm.FACTS_RULE,
        cv.get("extracted_text") or "", max_tokens=12000)
    structure = result.model_dump()
    prepo.set_cv_structure(cv_id, structure)
    return structure


# ── Proposals ──────────────────────────────────────────────────────────────────

ChangeType = Literal["reword", "reorder", "promote_skill", "drop", "add_project"]


class Proposal(BaseModel):
    section: str = Field(description="Exact section title from the CV structure")
    change_type: ChangeType
    original_text: str = Field(default="", description="Exact existing bullet text (reword, drop, promote_skill)")
    proposed_text: str = Field(default="", description="New bullet text; for add_project 'Name\\nbullet\\nbullet'; "
                                                       "for reorder the word 'top'")
    reason: str
    evidence: list[str] = Field(default_factory=list, description="Where the fact comes from: cv, note, github:<repo>, "
                                                                   "manual:<project>, linkedin")


class Proposals(BaseModel):
    proposals: list[Proposal]


PROPOSE_SYSTEM = (
    "You tailor a CV for a target set of jobs. Propose specific, small changes. Allowed change types: "
    "reword (rewrite one existing bullet to highlight relevant skills; same facts), "
    "reorder (move a whole section to the top, proposed_text='top'), "
    "promote_skill (move an existing skill line to the top of the Skills section), "
    "drop (remove an irrelevant bullet), "
    "add_project (add a project the candidate actually did, from the profile's projects or selected repos). "
    "original_text must match an existing bullet exactly for reword, drop and promote_skill. "
    "Every proposal needs a reason and evidence. Propose 5 to 15 changes. " + llm.FACTS_RULE
)


def _bullets(structure: dict) -> set[str]:
    return {normalize_text(b) for s in structure.get("sections") or [] for it in s.get("items") or []
            for b in it.get("bullets") or []}


def _valid(p: Proposal, structure: dict, sections: set[str], bullets: set[str]) -> bool:
    if p.change_type in ("reword", "drop", "promote_skill"):
        return normalize_text(p.original_text) in bullets and (p.change_type == "drop" or bool(p.proposed_text.strip())
                                                                or p.change_type == "promote_skill")
    if p.change_type == "reorder":
        return normalize_text(p.section) in sections
    if p.change_type == "add_project":
        return bool(p.proposed_text.strip()) and bool(p.evidence)
    return False


async def propose_changes(job_group_id: int | None = None, job_id: int | None = None,
                          cv_id: int | None = None) -> dict:
    if not job_group_id and not job_id:
        raise ValueError("Pick a job group or a single job")
    cv = prepo.get_cv(cv_id) if cv_id else prepo.get_primary_cv()
    if not cv:
        raise ValueError("Upload a CV first")
    profile = prepo.get_current_profile()
    if not profile:
        raise ValueError("Build your profile first")
    structure = current_structure()
    if job_group_id:
        group = crepo.get_group(job_group_id)
        if not group:
            raise LookupError("Job group not found")
        jobs = group["jobs"]
        target = f"Job group '{group['name']}': {group.get('summary') or ''}"
    else:
        j = repo.get_job(job_id)
        if not j:
            raise LookupError("Job not found")
        jobs = [j]
        target = f"Single job: {j['title']} at {j.get('company')}"
    job_text = "\n\n".join(f"{j['title']} at {j.get('company')}\n{(j.get('description') or '')[:2500]}" for j in jobs[:8])
    notes = [n["note"] for n in cv.get("notes") or []]
    result = await _run_llm(
        Proposals, PROPOSE_SYSTEM,
        f"{target}\n\nTarget jobs:\n{job_text}\n\nCurrent CV structure:\n{to_json(structure)}\n\n"
        f"Candidate profile (allowed facts):\n{to_json(profile['profile'])}\n\nCandidate notes:\n" + "\n".join(notes),
        max_tokens=10000)
    sections = {normalize_text(s["title"]) for s in structure.get("sections") or []}
    bullets = _bullets(structure)
    kept = [p.model_dump() for p in result.proposals if _valid(p, structure, sections, bullets)]
    version = crepo.create_version(cv["id"], job_group_id, job_id, kept)
    version["discarded"] = len(result.proposals) - len(kept)
    repo.add_audit("propose_cv_changes", "cv_version", version["id"],
                   {"proposals": len(kept), "discarded": version["discarded"]})
    return version


def decide(proposal_id: int, approve: bool) -> dict:
    row = crepo.decide_proposal(proposal_id, "approved" if approve else "rejected")
    if not row:
        raise LookupError("Proposal not found")
    repo.add_audit("approve_change" if approve else "reject_change", "cv_change_proposal", proposal_id)
    return row


def decide_all(version_id: int, approve: bool) -> int:
    n = crepo.decide_all(version_id, "approved" if approve else "rejected")
    repo.add_audit("approve_all_changes" if approve else "reject_all_changes", "cv_version", version_id, {"count": n})
    return n


# ── Apply and render ───────────────────────────────────────────────────────────

def _find_section(cv: dict, title: str) -> dict | None:
    key = normalize_text(title)
    for s in cv["sections"]:
        if normalize_text(s["title"]) == key:
            return s
    return None


def apply_changes(structure: dict, proposals: list[dict]) -> dict:
    """Apply approved proposals to a copy of the structure. Unapproved proposals are ignored."""
    cv = copy.deepcopy(structure)
    for p in proposals:
        if p["status"] != "approved":
            continue
        kind, orig = p["change_type"], normalize_text(p.get("original_text"))
        if kind in ("reword", "drop"):
            for s in cv["sections"]:
                for it in s["items"]:
                    for i, b in enumerate(it["bullets"]):
                        if normalize_text(b) == orig:
                            if kind == "reword":
                                it["bullets"][i] = p["proposed_text"]
                            else:
                                it["bullets"][i] = None
                    it["bullets"] = [b for b in it["bullets"] if b is not None]
        elif kind == "promote_skill":
            sec = _find_section(cv, p["section"]) or _find_section(cv, "Skills")
            if sec:
                for it in sec["items"]:
                    for i, b in enumerate(it["bullets"]):
                        if normalize_text(b) == orig:
                            it["bullets"].insert(0, it["bullets"].pop(i))
                            break
        elif kind == "reorder":
            sec = _find_section(cv, p["section"])
            if sec:
                cv["sections"].remove(sec)
                insert_at = 1 if cv["sections"] and "summary" in normalize_text(cv["sections"][0]["title"]) else 0
                cv["sections"].insert(insert_at, sec)
        elif kind == "add_project":
            lines = [x.strip(" -\u2022") for x in (p.get("proposed_text") or "").splitlines() if x.strip()]
            if not lines:
                continue
            sec = _find_section(cv, p["section"]) or _find_section(cv, "Projects")
            if not sec:
                sec = {"title": "Projects", "items": []}
                cv["sections"].append(sec)
            sec["items"].append({"heading": lines[0], "subheading": "", "dates": "", "bullets": lines[1:]})
    return cv


def tailored_cv(version: dict) -> dict:
    """What the preview and the files show: your saved edits if any, else the approved changes applied to the
    current profile."""
    if version.get("draft"):
        return version["draft"]
    return apply_changes(current_structure(), version["proposals"])


def preview(version_id: int) -> dict:
    version = crepo.get_version(version_id)
    if not version:
        raise LookupError("CV version not found")
    cv = tailored_cv(version)
    extras = cv_render.load_extras()
    photo = cv_render.photo_data_uri(cv.get("name") or "")
    pending = sum(1 for p in version["proposals"] if p["status"] == "proposed")
    return {"version_id": version_id, "html": cv_render.html_document(cv, extras, photo), "structure": cv,
            "has_edits": bool(version.get("draft")), "pending_changes": pending,
            "status": version["status"]}


def save_draft(version_id: int, structure: dict) -> dict:
    """Save your edits. Only sections with a title and a list of items are accepted."""
    sections = structure.get("sections")
    if not isinstance(sections, list):
        raise ValueError("The CV needs a list of sections")
    clean = {"name": str(structure.get("name") or "")[:200], "headline": str(structure.get("headline") or "")[:300],
             "contact": [], "sections": []}
    for s in sections:
        items = []
        for it in s.get("items") or []:
            items.append({"heading": str(it.get("heading") or "")[:2000],
                          "subheading": str(it.get("subheading") or "")[:500],
                          "dates": str(it.get("dates") or "")[:200],
                          "location": str(it.get("location") or "")[:200],
                          "bullets": [str(b)[:1500] for b in it.get("bullets") or [] if str(b).strip()]})
        clean["sections"].append({"title": str(s.get("title") or "")[:200], "items": items})
    if not crepo.set_draft(version_id, clean):
        raise LookupError("CV version not found")
    repo.add_audit("cv_preview_edit", "cv_version", version_id, {"sections": len(clean["sections"])})
    return preview(version_id)


def reset_draft(version_id: int) -> dict:
    if not crepo.set_draft(version_id, None):
        raise LookupError("CV version not found")
    return preview(version_id)


async def generate(version_id: int) -> dict:
    """Approve and create the files from the preview (your edits if any). Blocked while changes are undecided."""
    version = crepo.get_version(version_id)
    if not version:
        raise LookupError("CV version not found")
    pending = [p for p in version["proposals"] if p["status"] == "proposed"]
    if pending:
        raise ValueError(f"{len(pending)} change(s) still need your decision before the CV can be generated")
    tailored = tailored_cv(version)
    extras = cv_render.load_extras()
    label = version.get("group_name") or version.get("job_title") or f"version-{version_id}"
    stem = f"cv_{slugify(label)}-{date.today().isoformat()}-v{version_id}"
    docx_path, pdf_path = OUTPUTS_DIR / f"{stem}.docx", OUTPUTS_DIR / f"{stem}.pdf"
    cv_render.render_docx(tailored, extras, docx_path)
    cv_render.render_pdf(tailored, extras, pdf_path)
    crepo.mark_generated(version_id, str(docx_path), str(pdf_path))
    approved = sum(1 for p in version["proposals"] if p["status"] == "approved")
    repo.add_audit("generate_cv", "cv_version", version_id, {"approved_changes": approved, "file": stem})
    return crepo.get_version(version_id)


def output_file(version_id: int, kind: str) -> Path:
    version = crepo.get_version(version_id)
    if not version:
        raise LookupError("CV version not found")
    path = version.get("docx_path" if kind == "docx" else "pdf_path")
    if not path or not Path(path).is_file():
        raise LookupError("This CV version has not been generated yet")
    p = Path(path).resolve()
    if OUTPUTS_DIR.resolve() not in p.parents:
        raise PermissionError("File is outside the outputs folder")
    return p
