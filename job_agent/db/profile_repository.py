"""Data access for CVs, notes, LinkedIn sources, GitHub, manual projects, profiles, ATS boards."""

from __future__ import annotations

from sqlalchemy import select, update

from db.models import (
    AtsBoard,
    CvDocument,
    CvNote,
    GithubAccount,
    GithubRepo,
    LinkedinSource,
    ManualProject,
    Profile,
)
from db.repositories import _row
from db.session import session_scope
from utils import from_json, to_json, utcnow

# ── CVs and notes ──────────────────────────────────────────────────────────────


def find_cv_by_hash(sha: str) -> dict | None:
    with session_scope() as s:
        row = s.scalar(select(CvDocument).where(CvDocument.sha256 == sha))
        return _row(row, json_fields=("structure_json",)) if row else None


def add_cv(file_name: str, file_path: str, file_type: str, sha: str, text: str) -> dict:
    with session_scope() as s:
        has_primary = s.scalar(select(CvDocument.id).where(CvDocument.is_primary.is_(True)).limit(1))
        row = CvDocument(file_name=file_name, file_path=file_path, file_type=file_type, sha256=sha,
                         extracted_text=text, is_primary=not has_primary)
        s.add(row)
        s.flush()
        return _row(row, json_fields=("structure_json",))


def list_cvs() -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(select(CvDocument).order_by(CvDocument.created_at.desc())).all()
        out = []
        for r in rows:
            d = _row(r, json_fields=("structure_json",))
            d["has_structure"] = bool(d.pop("structure"))
            d["text_chars"] = len(d.pop("extracted_text") or "")
            d["notes"] = [_row(n) for n in s.scalars(select(CvNote).where(CvNote.cv_document_id == r.id)
                                                      .order_by(CvNote.created_at)).all()]
            out.append(d)
        return out


def get_cv(cv_id: int) -> dict | None:
    with session_scope() as s:
        row = s.get(CvDocument, cv_id)
        if not row:
            return None
        d = _row(row, json_fields=("structure_json",))
        d["notes"] = [_row(n) for n in s.scalars(select(CvNote).where(CvNote.cv_document_id == cv_id)).all()]
        return d


def get_primary_cv() -> dict | None:
    with session_scope() as s:
        cv_id = s.scalar(select(CvDocument.id).where(CvDocument.is_primary.is_(True)).limit(1))
    return get_cv(cv_id) if cv_id else None


def set_primary_cv(cv_id: int) -> bool:
    with session_scope() as s:
        if not s.get(CvDocument, cv_id):
            return False
        s.execute(update(CvDocument).values(is_primary=False))
        s.get(CvDocument, cv_id).is_primary = True
        return True


def set_cv_structure(cv_id: int, structure: dict) -> None:
    with session_scope() as s:
        row = s.get(CvDocument, cv_id)
        if row:
            row.structure_json = to_json(structure)


def delete_cv(cv_id: int) -> dict | None:
    with session_scope() as s:
        row = s.get(CvDocument, cv_id)
        if not row:
            return None
        d = _row(row)
        s.delete(row)
        return d


def add_cv_note(cv_id: int, note: str) -> dict | None:
    with session_scope() as s:
        if not s.get(CvDocument, cv_id):
            return None
        n = CvNote(cv_document_id=cv_id, note=note)
        s.add(n)
        s.flush()
        return _row(n)


def delete_cv_note(note_id: int) -> bool:
    with session_scope() as s:
        n = s.get(CvNote, note_id)
        if not n:
            return False
        s.delete(n)
        return True


def all_cv_notes() -> list[dict]:
    with session_scope() as s:
        return [_row(n) for n in s.scalars(select(CvNote).order_by(CvNote.created_at)).all()]


# ── LinkedIn ───────────────────────────────────────────────────────────────────

def add_linkedin_source(source_type: str, raw: dict, file_path: str | None = None) -> dict:
    with session_scope() as s:
        row = LinkedinSource(source_type=source_type, file_path=file_path, raw_json=to_json(raw), fetched_at=utcnow())
        s.add(row)
        s.flush()
        return _row(row, json_fields=("raw_json",))


def list_linkedin_sources(include_raw: bool = False) -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(select(LinkedinSource).order_by(LinkedinSource.created_at.desc())).all()
        out = []
        for r in rows:
            d = _row(r, json_fields=("raw_json",))
            if not include_raw:
                raw = d.pop("raw") or {}
                d["summary"] = {k: (len(v) if isinstance(v, (list, dict, str)) else v) for k, v in raw.items()}
            out.append(d)
        return out


def delete_linkedin_source(source_id: int) -> bool:
    with session_scope() as s:
        r = s.get(LinkedinSource, source_id)
        if not r:
            return False
        s.delete(r)
        return True


# ── GitHub ─────────────────────────────────────────────────────────────────────

_REPO_JSON = ("topics_json",)


def upsert_github_repos(account_type: str, login_or_org: str, repos: list[dict]) -> dict:
    """Store repos. New personal repos start selected (unless forks or zero commits); company repos start
    unselected. Existing selections are never overwritten by a re-sync."""
    added = 0
    with session_scope() as s:
        acct = s.scalar(select(GithubAccount).where(GithubAccount.account_type == account_type,
                                                    GithubAccount.login_or_org == login_or_org))
        if not acct:
            acct = GithubAccount(account_type=account_type, login_or_org=login_or_org)
            s.add(acct)
            s.flush()
        acct.last_synced_at = utcnow()
        for r in repos:
            row = s.scalar(select(GithubRepo).where(GithubRepo.github_account_id == acct.id,
                                                    GithubRepo.full_name == r["full_name"]))
            meta = {"topics": r.get("topics") or [], "description": r.get("description") or "",
                    "fork": r.get("fork"), "archived": r.get("archived")}
            if row:
                old = from_json(row.topics_json, {}) or {}
                meta["languages"] = old.get("languages") or {}
                row.is_private = r["is_private"]
                row.primary_language = r.get("primary_language")
                row.last_pushed_at = r.get("last_pushed_at")
                row.my_commit_count = r.get("my_commit_count")
                row.topics_json = to_json(meta)
                continue
            selected = (account_type == "personal" and not r.get("fork") and r.get("my_commit_count") != 0)
            s.add(GithubRepo(github_account_id=acct.id, full_name=r["full_name"], is_private=r["is_private"],
                             primary_language=r.get("primary_language"), topics_json=to_json(meta),
                             last_pushed_at=r.get("last_pushed_at"), my_commit_count=r.get("my_commit_count"),
                             is_selected=selected, llm_allowed=(account_type == "personal")))
            added += 1
        return {"account_id": acct.id, "added": added, "total": len(repos)}


def list_github_repos(account_type: str | None = None, selected_only: bool = False) -> list[dict]:
    with session_scope() as s:
        stmt = select(GithubRepo, GithubAccount).join(GithubAccount, GithubRepo.github_account_id == GithubAccount.id)
        if account_type:
            stmt = stmt.where(GithubAccount.account_type == account_type)
        if selected_only:
            stmt = stmt.where(GithubRepo.is_selected.is_(True))
        out = []
        for repo, acct in s.execute(stmt.order_by(GithubRepo.last_pushed_at.desc())).all():
            d = _row(repo, json_fields=_REPO_JSON)
            d["account_type"] = acct.account_type
            d["account"] = acct.login_or_org
            d["readme_chars"] = len(d.pop("readme_text") or "")
            out.append(d)
        return out


def set_repo_flags(repo_id: int, is_selected: bool | None = None, llm_allowed: bool | None = None) -> dict | None:
    with session_scope() as s:
        r = s.get(GithubRepo, repo_id)
        if not r:
            return None
        if is_selected is not None:
            r.is_selected = is_selected
        if llm_allowed is not None:
            r.llm_allowed = llm_allowed
        s.flush()
        return _row(r, json_fields=_REPO_JSON)


def set_repo_details(repo_id: int, readme_text: str, languages: dict, code: dict | None = None) -> None:
    """Store README, languages and the code summary. The code summary lives in topics_json, so no
    schema change is needed."""
    with session_scope() as s:
        r = s.get(GithubRepo, repo_id)
        if r:
            meta = from_json(r.topics_json, {}) or {}
            meta["languages"] = languages
            if code is not None:
                meta["code"] = code
            r.topics_json = to_json(meta)
            r.readme_text = readme_text


def repos_for_profile() -> list[dict]:
    """Selected repos with their README. Company repos only when llm_allowed is set."""
    with session_scope() as s:
        stmt = (select(GithubRepo, GithubAccount).join(GithubAccount, GithubRepo.github_account_id == GithubAccount.id)
                .where(GithubRepo.is_selected.is_(True)))
        out = []
        for repo, acct in s.execute(stmt).all():
            d = _row(repo, json_fields=_REPO_JSON)
            d["account_type"] = acct.account_type
            d["send_to_llm"] = acct.account_type == "personal" or repo.llm_allowed
            out.append(d)
        return out


# ── Manual projects ────────────────────────────────────────────────────────────

def add_manual_project(data: dict) -> dict:
    with session_scope() as s:
        p = ManualProject(title=data["title"], description=data["description"],
                          tech_json=to_json(data.get("tech") or []), url=data.get("url") or None)
        s.add(p)
        s.flush()
        return _row(p, json_fields=("tech_json",))


def list_manual_projects() -> list[dict]:
    with session_scope() as s:
        return [_row(p, json_fields=("tech_json",))
                for p in s.scalars(select(ManualProject).order_by(ManualProject.created_at.desc())).all()]


def delete_manual_project(project_id: int) -> bool:
    with session_scope() as s:
        p = s.get(ManualProject, project_id)
        if not p:
            return False
        s.delete(p)
        return True


# ── Profiles ───────────────────────────────────────────────────────────────────

def save_profile(profile: dict, source_ids: dict) -> dict:
    with session_scope() as s:
        latest = s.scalar(select(Profile.version).order_by(Profile.version.desc()).limit(1)) or 0
        s.execute(update(Profile).values(is_current=False))
        p = Profile(version=latest + 1, profile_json=to_json(profile), source_ids_json=to_json(source_ids),
                    is_current=True)
        s.add(p)
        s.flush()
        return _row(p, json_fields=("profile_json", "source_ids_json"))


def get_current_profile() -> dict | None:
    with session_scope() as s:
        p = s.scalar(select(Profile).where(Profile.is_current.is_(True)).limit(1))
        return _row(p, json_fields=("profile_json", "source_ids_json")) if p else None


def get_profile_version(version: int) -> dict | None:
    with session_scope() as s:
        p = s.scalar(select(Profile).where(Profile.version == version).limit(1))
        return _row(p, json_fields=("profile_json", "source_ids_json")) if p else None


def update_current_profile(profile: dict) -> dict | None:
    with session_scope() as s:
        p = s.scalar(select(Profile).where(Profile.is_current.is_(True)).limit(1))
        if not p:
            return None
        p.profile_json = to_json(profile)
        s.flush()
        return _row(p, json_fields=("profile_json", "source_ids_json"))


# ── ATS boards ─────────────────────────────────────────────────────────────────

def add_ats_board(provider: str, board_token: str, company_name: str) -> tuple[dict, bool]:
    with session_scope() as s:
        row = s.scalar(select(AtsBoard).where(AtsBoard.provider == provider, AtsBoard.board_token == board_token))
        if row:
            row.is_active = True
            if company_name:
                row.company_name = company_name
            s.flush()
            return _row(row), False
        row = AtsBoard(provider=provider, board_token=board_token, company_name=company_name or board_token)
        s.add(row)
        s.flush()
        return _row(row), True


def list_ats_boards(active_only: bool = False) -> list[dict]:
    with session_scope() as s:
        stmt = select(AtsBoard).order_by(AtsBoard.company_name)
        if active_only:
            stmt = stmt.where(AtsBoard.is_active.is_(True))
        return [_row(r) for r in s.scalars(stmt).all()]


def touch_ats_board(board_id: int) -> None:
    with session_scope() as s:
        r = s.get(AtsBoard, board_id)
        if r:
            r.last_checked_at = utcnow()


def delete_ats_board(board_id: int) -> bool:
    with session_scope() as s:
        r = s.get(AtsBoard, board_id)
        if not r:
            return False
        s.delete(r)
        return True
