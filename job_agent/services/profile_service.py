"""Profile intake: CV upload and notes, LinkedIn (Apify, export, PDF), GitHub, manual projects,
profile building and target-role proposals."""

from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path

from pydantic import BaseModel, Field

import llm
from clients import apify_linkedin, github
from config import UPLOADS_DIR, settings
from db import profile_repository as prepo
from db import repositories as repo
from documents import ALLOWED_TYPES, MAX_UPLOAD_BYTES, extract_text, safe_filename
from utils import sha256_text, to_json

# ── CV upload ──────────────────────────────────────────────────────────────────


def upload_cv(file_name: str, data: bytes, note: str = "") -> dict:
    ext = Path(file_name).suffix.lower()
    if ext not in ALLOWED_TYPES:
        raise ValueError("Upload a PDF or DOCX file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("File is larger than 10 MB")
    if not data:
        raise ValueError("File is empty")
    import hashlib

    sha = hashlib.sha256(data).hexdigest()
    existing = prepo.find_cv_by_hash(sha)
    if existing:
        if note.strip():
            prepo.add_cv_note(existing["id"], note.strip())
        return {**prepo.get_cv(existing["id"]), "duplicate": True}
    file_type = ALLOWED_TYPES[ext]
    try:
        text = extract_text(data, file_type)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Could not read the {file_type.upper()} file ({type(exc).__name__})") from exc
    path = UPLOADS_DIR / "cv" / f"{sha[:12]}_{safe_filename(file_name)}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    row = prepo.add_cv(file_name, str(path), file_type, sha, text)
    if note.strip():
        prepo.add_cv_note(row["id"], note.strip())
    repo.add_audit("upload_cv", "cv_document", row["id"], {"file_name": file_name})
    out = prepo.get_cv(row["id"])
    out["duplicate"] = False
    out["warning"] = "" if len(text) > 200 else "Very little text was extracted. A scanned PDF needs a text-based version."
    return out


# ── LinkedIn ───────────────────────────────────────────────────────────────────

LINKEDIN_EXPORT_FILES = ("profile", "positions", "education", "skills", "projects", "certifications",
                         "languages", "honors", "courses", "publications", "recommendations_received",
                         "shares")  # shares = your own posts and reposts (ShareCommentary column)


def _csv_rows(text: str) -> list[dict]:
    # LinkedIn exports sometimes start with "Notes:" lines before the header.
    lines = text.splitlines()
    while lines and not ("," in lines[0] and not lines[0].lower().startswith("notes")):
        lines.pop(0)
    return [dict(r) for r in csv.DictReader(io.StringIO("\n".join(lines)))][:500]


def upload_linkedin_export(file_name: str, data: bytes) -> dict:
    """Accept the LinkedIn data export ZIP, or one of its CSV files."""
    if len(data) > 50 * 1024 * 1024:
        raise ValueError("File is larger than 50 MB")
    tables: dict[str, list[dict]] = {}
    lower = file_name.lower()
    if lower.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for name in zf.namelist():
                stem = Path(name).stem.lower().replace(" ", "_")
                if name.lower().endswith(".csv") and stem in LINKEDIN_EXPORT_FILES:
                    tables[stem] = _csv_rows(zf.read(name).decode("utf-8-sig", errors="replace"))
    elif lower.endswith(".csv"):
        tables[Path(file_name).stem.lower().replace(" ", "_")] = _csv_rows(data.decode("utf-8-sig", errors="replace"))
    else:
        raise ValueError("Upload the LinkedIn export .zip or a .csv from it")
    if not tables:
        raise ValueError("No profile CSVs found (expected Profile.csv, Positions.csv, Skills.csv, ...)")
    return prepo.add_linkedin_source("export_csv", tables)


def upload_linkedin_pdf(file_name: str, data: bytes) -> dict:
    if not file_name.lower().endswith(".pdf"):
        raise ValueError("Upload the PDF saved from your LinkedIn profile (More > Save to PDF)")
    text = extract_text(data, "pdf")
    path = UPLOADS_DIR / "linkedin" / f"{sha256_text(text)[:12]}_{safe_filename(file_name)}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return prepo.add_linkedin_source("pdf", {"text": text}, str(path))


async def fetch_linkedin_apify(profile_url: str | None = None) -> dict:
    url = (profile_url or settings.LINKEDIN_PROFILE_URL or "").strip()
    res = await apify_linkedin.fetch_profile(url)
    repo.record_usage("apify", "linkedin-profile-scraper", 1 if "item" in res else 0, None,
                      res.get("error", ""))
    if "error" in res:
        raise ValueError(res["error"])
    return prepo.add_linkedin_source("apify", {"profile_url": url, **res["item"]})


# ── GitHub ─────────────────────────────────────────────────────────────────────

async def sync_github(account_type: str) -> dict:
    if account_type not in ("personal", "company"):
        raise ValueError("account_type must be personal or company")
    res = await github.list_repos(account_type)
    if "error" in res:
        raise ValueError(res["error"])
    repo.record_usage("github", f"{account_type}/repos", 0, 200, f"{len(res['repos'])} repos")
    stored = prepo.upsert_github_repos(account_type, res["login_or_org"], res["repos"])
    return {**stored, "author_login": res["author_login"], "repos": prepo.list_github_repos(account_type)}


async def _load_repo_details(repos: list[dict]) -> None:
    import asyncio

    async def one(r: dict):
        topics = r.get("topics") if isinstance(r.get("topics"), dict) else {}
        if r.get("readme_text") and "code" in topics:  # already read, including the code summary
            return
        d = await github.repo_details(r["account_type"], r["full_name"])
        prepo.set_repo_details(r["id"], d["readme_text"], d["languages"], d.get("code"))
        r["readme_text"] = d["readme_text"]
        r["topics"] = {**topics, "languages": d["languages"], "code": d.get("code")}

    await asyncio.gather(*(one(r) for r in repos if r["send_to_llm"]))


# ── Profile building ───────────────────────────────────────────────────────────

class Experience(BaseModel):
    employer: str = ""
    title: str = ""
    start: str = ""
    end: str = ""
    location: str = ""
    highlights: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)


class Project(BaseModel):
    name: str
    description: str = ""
    technologies: list[str] = Field(default_factory=list)
    source: str = Field(default="", description="cv | github:<repo full name> | manual | linkedin")
    url: str = ""


class Education(BaseModel):
    institution: str = ""
    degree: str = ""
    year: str = ""


class CandidateProfile(BaseModel):
    full_name: str = ""
    headline: str = ""
    summary: str = ""
    current_title: str = ""
    total_years_experience: float | None = None
    locations: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list, description="Wishes stated in the user's notes")
    target_role_hints: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list, description="Things that are unclear or conflicting")


from prompts import PROFILE_BUILDER_PROMPT as PROFILE_SYSTEM  # noqa: E402


def _cap(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n] + "\n[truncated]"


# Image, logo and media fields in LinkedIn data take most of the characters but say nothing about the person.
_LINKEDIN_NOISE_KEYS = re.compile(r"logo|picture|image|media|sizes|photo|background|cover|avatar|thumbnail|"
                                  r"profilepic|backgroundpic", re.I)


def _compact_linkedin(value):
    """Drop empty values and image/media fields, so the text that matters fits the build's size cap."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if _LINKEDIN_NOISE_KEYS.search(str(k)):
                continue
            cleaned = _compact_linkedin(v)
            if cleaned not in (None, "", [], {}):
                out[k] = cleaned
        return out
    if isinstance(value, list):
        return [c for c in (_compact_linkedin(v) for v in value) if c not in (None, "", [], {})]
    return value


async def build_profile() -> dict:
    cv = prepo.get_primary_cv()
    if not cv:
        raise ValueError("Upload a CV first")
    notes = [n["note"] for n in cv.get("notes") or []]
    linkedin = prepo.list_linkedin_sources(include_raw=True)
    repos = prepo.repos_for_profile()
    await _load_repo_details(repos)
    manual = prepo.list_manual_projects()

    def code_block(code: dict) -> str:
        if not code or code.get("error"):
            return f"code: not read ({(code or {}).get('error', 'no data')})"
        deps = "\n".join(f"{path}:\n{_cap(text, 800)}" for path, text in (code.get("dependencies") or {}).items())
        return (f"code: {code.get('file_count')} files, {code.get('python_file_count')} Python files "
                f"({code.get('sampled_python_files')} read)\n"
                f"imports actually used in the code: {', '.join(code.get('imports') or []) or 'none'}\n"
                f"AWS and framework words found in the code (imports are stronger evidence than mentions): "
                + ", ".join(f"{k} ({len(v)} files)" for k, v in (code.get("service_mentions") or {}).items())
                + f"\nfile tree (first 80): {', '.join((code.get('tree') or [])[:80])}"
                + (f"\ndependency files:\n{deps}" if deps else ""))

    def repo_block(r: dict) -> str:
        meta = r.get("topics") or {}
        return (f"### github:{r['full_name']}\ncommits by user: {r.get('my_commit_count')} | "
                f"primary language: {r.get('primary_language')} | languages: {meta.get('languages')} | "
                f"topics: {meta.get('topics')}\ndescription: {meta.get('description') or ''}\n"
                f"{code_block(meta.get('code') or {})}\n"
                f"README:\n{_cap(r.get('readme_text') or '', 2500)}")

    personal = [r for r in repos if r["account_type"] == "personal"]
    company_allowed = [r for r in repos if r["account_type"] == "company" and r["send_to_llm"]]
    company_names = [r["full_name"] for r in repos if r["account_type"] == "company" and not r["send_to_llm"]]

    parts = [f"## CV (file: {cv['file_name']})\n{_cap(cv.get('extracted_text') or '', 30000)}"]
    parts.append("## USER NOTES (authoritative)\n" + ("\n".join(f"- {n}" for n in notes) if notes else "(none)"))
    for src in linkedin[:3]:
        parts.append(f"## LINKEDIN (source: {src['source_type']})\n"
                     f"{_cap(to_json(_compact_linkedin(src.get('raw') or {})), 25000)}")
    if not linkedin:
        parts.append("## LINKEDIN\n(none)")
    parts.append("## PERSONAL GITHUB\n" + ("\n\n".join(repo_block(r) for r in personal[:30]) or "(none selected)"))
    parts.append("## COMPANY GITHUB (content allowed)\n"
                 + ("\n\n".join(repo_block(r) for r in company_allowed[:20]) or "(none)"))
    parts.append("## COMPANY GITHUB (names only)\n" + ("\n".join(f"- {n}" for n in company_names) or "(none)"))
    parts.append("## MANUAL PROJECTS\n" + ("\n".join(
        f"- {p['title']}: {p['description']} (tech: {', '.join(p.get('tech') or [])}; url: {p.get('url') or ''})"
        for p in manual) or "(none)"))

    profile = await _run_llm(CandidateProfile, PROFILE_SYSTEM,
                             "Build the candidate profile from this material.\n\n" + "\n\n".join(parts),
                             max_tokens=16000)
    source_ids = {"cv_document_id": cv["id"], "linkedin_source_ids": [s["id"] for s in linkedin[:3]],
                  "github_repo_ids": [r["id"] for r in repos], "manual_project_ids": [p["id"] for p in manual]}
    saved = prepo.save_profile(profile.model_dump(), source_ids)
    repo.add_audit("build_profile", "profile", saved["id"], source_ids)
    return saved


async def _run_llm(model, system: str, prompt: str, **kw):
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(llm.structured, model, system, prompt, **kw)


# ── Chat edits to the built profile ────────────────────────────────────────────

class ProfileEditResult(BaseModel):
    reply: str = ""
    changes: list[str] = Field(default_factory=list)
    profile: CandidateProfile


async def chat_edit_profile(message: str, save_as_note: bool = False) -> dict:
    """Apply the owner's instruction to the current profile. A change is saved as a new profile version,
    so the previous one is kept for undo. A question changes nothing."""
    from prompts import PROFILE_EDIT_PROMPT

    current = prepo.get_current_profile()
    if not current:
        raise ValueError("Build your profile first")
    message = message.strip()
    if not message:
        raise ValueError("Write what to change or ask")

    prompt = ("## CURRENT PROFILE (JSON)\n" + to_json(current["profile"])
              + "\n\n## OWNER'S INSTRUCTION\n" + message)
    from starlette.concurrency import run_in_threadpool

    from tools.list_github_repos import list_github_repos
    from tools.read_github_file import read_github_file
    from tools.read_github_repo import read_github_repo
    from tools.read_linkedin_posts import read_linkedin_posts

    result = await run_in_threadpool(llm.structured_with_tools, ProfileEditResult, PROFILE_EDIT_PROMPT, prompt,
                                     [list_github_repos, read_github_repo, read_github_file, read_linkedin_posts],
                                     max_tokens=10000)
    if not result.changes:
        return {"reply": result.reply, "changes": [], "saved": False, "version": current["version"],
                "note_saved": False}

    saved = prepo.save_profile(result.profile.model_dump(), current.get("source_ids") or {})
    note_saved = False
    if save_as_note:  # a CV note is read on every rebuild, so the change survives a rebuild
        cv = prepo.get_primary_cv()
        if cv:
            prepo.add_cv_note(cv["id"], message[:2000])
            note_saved = True
    repo.add_audit("profile_chat_edit", "profile", saved["id"],
                   {"from_version": current["version"], "instruction": message[:500], "changes": result.changes,
                    "note_saved": note_saved})
    return {"reply": result.reply, "changes": result.changes, "saved": True, "version": saved["version"],
            "from_version": current["version"], "note_saved": note_saved}


async def undo_last_profile_change() -> dict:
    """Make the previous profile version current again, as a new version (history is never deleted)."""
    current = prepo.get_current_profile()
    if not current:
        raise ValueError("No profile yet")
    previous = prepo.get_profile_version(current["version"] - 1)
    if not previous:
        raise ValueError("No earlier version to go back to")
    saved = prepo.save_profile(previous["profile"], previous.get("source_ids") or {})
    repo.add_audit("profile_undo", "profile", saved["id"], {"restored_from_version": previous["version"]})
    return {"version": saved["version"], "restored_from_version": previous["version"]}


# ── Target role proposals ──────────────────────────────────────────────────────

class RoleProposal(BaseModel):
    title: str
    seniority: str = ""
    locations: list[str] = Field(default_factory=list)
    remote_ok: bool = False
    onet_codes: list[str] = Field(default_factory=list, description="O*NET-SOC codes like 15-1252.00")
    why: str = ""


class RoleProposals(BaseModel):
    roles: list[RoleProposal]


async def propose_roles() -> list[dict]:
    profile = prepo.get_current_profile()
    if not profile:
        raise ValueError("Build your profile first")
    import onet

    codes = "\n".join(f"{c['code']} {c['name']}" for c in onet.all_codes())
    result = await _run_llm(
        RoleProposals,
        "You are a career advisor. Propose 3 to 5 realistic target job roles for this candidate, based only on "
        "their profile and stated preferences. Pick O*NET codes from the list provided.",
        f"Profile:\n{to_json(profile['profile'])}\n\nO*NET codes you may use:\n{codes}")
    created = []
    for r in result.roles:
        valid_codes = [c for c in r.onet_codes if re.fullmatch(r"\d{2}-\d{4}\.\d{2}", c)]
        row = repo.create_role({"title": r.title, "seniority": r.seniority, "locations": r.locations,
                                "remote_ok": r.remote_ok, "onet_codes": valid_codes, "status": "proposed"})
        created.append({**row, "why": r.why})
    return created
