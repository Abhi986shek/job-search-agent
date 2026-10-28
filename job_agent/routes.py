"""HTTP routes the Streamlit frontend calls. Thin: validate, call a service, return."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

import agent
import onet
from db import cv_repository as crepo
from db import outreach_repository as orepo
from db import profile_repository as prepo
from db import repositories as repo
from llm import LLMNotConfigured
from schemas import (
    ChatRequest,
    CompanyJobsRequest,
    GuidanceUrlBatch,
    JobUpdate,
    SearchRequest,
    TargetRoleIn,
    TargetRoleUpdate,
)
from services import cv_service, match_service, outreach_service, profile_service, search_service
from utils import is_http_url, logger, safe_error

router = APIRouter()


async def _call(fn, *args, **kwargs):
    """Run a service and map its errors to HTTP codes. Unexpected errors never leak their message."""
    try:
        result = fn(*args, **kwargs)
        if hasattr(result, "__await__"):
            result = await result
        return result
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except LLMNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    except (ValueError, PermissionError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("unhandled error in %s", getattr(fn, "__name__", fn))
        raise HTTPException(500, f"Internal error ({safe_error(exc)}). See job_agent/app.log.") from exc


def _not_found(value, what: str):
    if value in (None, False):
        raise HTTPException(404, f"{what} not found")
    return value


# ── Health and status ──────────────────────────────────────────────────────────

@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/status")
async def status() -> dict:
    return await _call(search_service.source_status)


@router.get("/usage")
def usage(days: int = Query(30, ge=1, le=365)) -> dict:
    return repo.usage_summary(days)


@router.get("/predictleads/request-logs")
async def predictleads_request_logs(since: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$")) -> dict:
    from clients import predictleads

    return await predictleads.request_logs(since)


# ── Target roles and O*NET ─────────────────────────────────────────────────────

@router.get("/onet/suggest")
def onet_suggest(title: str = Query(..., min_length=2)) -> dict:
    return {"suggested": onet.suggest(title), "all": onet.all_codes()}


@router.get("/roles")
def list_roles(status: str | None = None) -> list[dict]:
    return repo.list_roles(status)


@router.post("/roles")
def create_role(body: TargetRoleIn) -> dict:
    return repo.create_role(body.model_dump())


@router.post("/roles/propose")
async def propose_roles() -> list[dict]:
    return await _call(profile_service.propose_roles)


@router.patch("/roles/{role_id}")
def update_role(role_id: int, body: TargetRoleUpdate) -> dict:
    return _not_found(repo.update_role(role_id, body.model_dump(exclude_none=True)), "Role")


@router.delete("/roles/{role_id}")
def delete_role(role_id: int) -> dict:
    _not_found(repo.delete_role(role_id), "Role")
    return {"deleted": role_id}


# ── Searches and jobs ──────────────────────────────────────────────────────────

@router.post("/searches")
async def run_search(body: SearchRequest) -> dict:
    return await _call(search_service.run_search, body)


@router.get("/searches")
def list_searches(limit: int = Query(50, ge=1, le=500)) -> list[dict]:
    return repo.list_searches(limit)


@router.get("/searches/{search_id}")
def get_search(search_id: int) -> dict:
    return _not_found(repo.get_search(search_id), "Search")


@router.post("/companies/jobs")
async def company_jobs(body: CompanyJobsRequest) -> dict:
    return await _call(search_service.company_jobs, body.domain, body.limit)


@router.get("/jobs")
def list_jobs(status: str | None = None, source: str | None = None, q: str | None = None,
              search_id: int | None = None, limit: int = Query(200, ge=1, le=1000),
              offset: int = Query(0, ge=0)) -> dict:
    return repo.list_jobs(status=status, source=source, q=q, search_id=search_id, limit=limit, offset=offset)


# Declared before /jobs/{job_id} so "duplicates" is not read as a job id.
@router.get("/jobs/duplicates")
def possible_duplicates(threshold: float = Query(0.75, ge=0.5, le=1.0),
                        limit: int = Query(100, ge=1, le=500)) -> list[dict]:
    return repo.possible_duplicates(threshold, limit)


class JobPairIn(BaseModel):
    job_a: int
    job_b: int


@router.post("/jobs/duplicates/dismiss")
def dismiss_duplicate(body: JobPairIn) -> dict:
    repo.mark_not_duplicate(body.job_a, body.job_b)
    return {"dismissed": [body.job_a, body.job_b]}


class JobMergeIn(BaseModel):
    merge_job_id: int = Field(description="This job is merged into the job in the path and then removed")


@router.post("/jobs/{job_id}/merge")
async def merge_job(job_id: int, body: JobMergeIn) -> dict:
    return _not_found(await _call(repo.merge_jobs, job_id, body.merge_job_id), "Job")


@router.get("/jobs/{job_id}")
def get_job(job_id: int) -> dict:
    return _not_found(repo.get_job(job_id), "Job")


@router.patch("/jobs/{job_id}")
def update_job(job_id: int, body: JobUpdate) -> dict:
    return _not_found(repo.update_job_status(job_id, body.status), "Job")


@router.post("/jobs/{job_id}/predictleads-details")
async def job_predictleads_details(job_id: int) -> dict:
    return await _call(search_service.predictleads_job_details, job_id)


# ── Guidance URLs ──────────────────────────────────────────────────────────────

@router.post("/guidance-urls")
def add_guidance_urls(body: GuidanceUrlBatch) -> list[dict]:
    bad = [i.url for i in body.items if not is_http_url(i.url)]
    if bad:
        raise HTTPException(400, f"Not valid http(s) URLs: {', '.join(bad[:5])}")
    return search_service.add_guidance_urls([i.model_dump() for i in body.items])


@router.get("/guidance-urls")
def list_guidance_urls() -> list[dict]:
    return repo.list_guidance_urls()


@router.delete("/guidance-urls/{guidance_id}")
def delete_guidance_url(guidance_id: int) -> dict:
    _not_found(repo.delete_guidance_url(guidance_id), "Guidance URL")
    return {"deleted": guidance_id}


# ── ATS boards ─────────────────────────────────────────────────────────────────

class AtsBoardIn(BaseModel):
    provider: Literal["greenhouse", "lever", "ashby"]
    board_token: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._-]+$")
    company_name: str = Field(default="", max_length=300)


@router.get("/ats-boards")
def list_ats_boards() -> list[dict]:
    return prepo.list_ats_boards()


@router.post("/ats-boards")
async def add_ats_board(body: AtsBoardIn) -> dict:
    row, created = prepo.add_ats_board(body.provider, body.board_token, body.company_name)
    check = await _call(search_service.ats_board_jobs, row["id"])
    return {**row, "created": created, "check": check}


@router.post("/ats-boards/{board_id}/refresh")
async def refresh_ats_board(board_id: int) -> dict:
    return await _call(search_service.ats_board_jobs, board_id)


@router.delete("/ats-boards/{board_id}")
def delete_ats_board(board_id: int) -> dict:
    _not_found(prepo.delete_ats_board(board_id), "ATS board")
    return {"deleted": board_id}


# ── CVs and notes ──────────────────────────────────────────────────────────────

@router.post("/cvs")
async def upload_cv(file: UploadFile = File(...), note: str = Form("")) -> dict:
    data = await file.read()
    return await _call(profile_service.upload_cv, file.filename or "cv", data, note)


@router.get("/cvs")
def list_cvs() -> list[dict]:
    return prepo.list_cvs()


@router.get("/cvs/{cv_id}")
def get_cv(cv_id: int) -> dict:
    return _not_found(prepo.get_cv(cv_id), "CV")


@router.post("/cvs/{cv_id}/primary")
def set_primary_cv(cv_id: int) -> dict:
    _not_found(prepo.set_primary_cv(cv_id), "CV")
    return {"primary": cv_id}


@router.post("/cvs/{cv_id}/structure")
async def structure_cv(cv_id: int, force: bool = False) -> dict:
    return await _call(cv_service.ensure_structure, cv_id, force)


@router.delete("/cvs/{cv_id}")
def delete_cv(cv_id: int) -> dict:
    _not_found(prepo.delete_cv(cv_id), "CV")
    return {"deleted": cv_id}


class NoteIn(BaseModel):
    note: str = Field(min_length=1, max_length=5000)


@router.post("/cvs/{cv_id}/notes")
def add_cv_note(cv_id: int, body: NoteIn) -> dict:
    return _not_found(prepo.add_cv_note(cv_id, body.note.strip()), "CV")


@router.delete("/cv-notes/{note_id}")
def delete_cv_note(note_id: int) -> dict:
    _not_found(prepo.delete_cv_note(note_id), "Note")
    return {"deleted": note_id}


# ── LinkedIn ───────────────────────────────────────────────────────────────────

class LinkedinApifyIn(BaseModel):
    profile_url: str = Field(default="", max_length=500)


@router.post("/linkedin/apify")
async def linkedin_apify(body: LinkedinApifyIn) -> dict:
    return await _call(profile_service.fetch_linkedin_apify, body.profile_url or None)


@router.post("/linkedin/export")
async def linkedin_export(file: UploadFile = File(...)) -> dict:
    data = await file.read()
    return await _call(profile_service.upload_linkedin_export, file.filename or "", data)


@router.post("/linkedin/pdf")
async def linkedin_pdf(file: UploadFile = File(...)) -> dict:
    data = await file.read()
    return await _call(profile_service.upload_linkedin_pdf, file.filename or "", data)


@router.get("/linkedin")
def list_linkedin() -> list[dict]:
    return prepo.list_linkedin_sources()


@router.delete("/linkedin/{source_id}")
def delete_linkedin(source_id: int) -> dict:
    _not_found(prepo.delete_linkedin_source(source_id), "LinkedIn source")
    return {"deleted": source_id}


# ── GitHub ─────────────────────────────────────────────────────────────────────

@router.post("/github/{account_type}/sync")
async def github_sync(account_type: Literal["personal", "company"]) -> dict:
    return await _call(profile_service.sync_github, account_type)


@router.get("/github/repos")
def github_repos(account_type: Literal["personal", "company"] | None = None) -> list[dict]:
    return prepo.list_github_repos(account_type)


class RepoFlags(BaseModel):
    is_selected: bool | None = None
    llm_allowed: bool | None = None


@router.patch("/github/repos/{repo_id}")
def github_repo_flags(repo_id: int, body: RepoFlags) -> dict:
    return _not_found(prepo.set_repo_flags(repo_id, body.is_selected, body.llm_allowed), "Repo")


class RepoBulk(BaseModel):
    repo_ids: list[int]
    is_selected: bool


@router.post("/github/repos/bulk")
def github_repo_bulk(body: RepoBulk) -> dict:
    n = sum(1 for rid in body.repo_ids if prepo.set_repo_flags(rid, is_selected=body.is_selected))
    return {"updated": n}


# ── Manual projects ────────────────────────────────────────────────────────────

class ManualProjectIn(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    description: str = Field(min_length=10, max_length=5000)
    tech: list[str] = Field(default_factory=list)
    url: str = Field(default="", max_length=1000)


@router.get("/projects")
def list_projects() -> list[dict]:
    return prepo.list_manual_projects()


@router.post("/projects")
def add_project(body: ManualProjectIn) -> dict:
    return prepo.add_manual_project(body.model_dump())


@router.delete("/projects/{project_id}")
def delete_project(project_id: int) -> dict:
    _not_found(prepo.delete_manual_project(project_id), "Project")
    return {"deleted": project_id}


# ── Profile ────────────────────────────────────────────────────────────────────

@router.post("/profile/build")
async def build_profile() -> dict:
    return await _call(profile_service.build_profile)


@router.get("/profile")
def get_profile() -> dict:
    return prepo.get_current_profile() or {}


class ProfileEdit(BaseModel):
    profile: dict


@router.put("/profile")
def edit_profile(body: ProfileEdit) -> dict:
    return _not_found(prepo.update_current_profile(body.profile), "Profile")


class ProfileChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    save_as_note: bool = Field(default=False, description="Also save the instruction as a CV note, so rebuilds keep it")


@router.post("/profile/chat")
async def profile_chat(body: ProfileChatIn) -> dict:
    return await _call(profile_service.chat_edit_profile, body.message, body.save_as_note)


@router.post("/profile/undo")
async def profile_undo() -> dict:
    return await _call(profile_service.undo_last_profile_change)


# ── Matching ───────────────────────────────────────────────────────────────────

class MatchIn(BaseModel):
    job_ids: list[int] = Field(default_factory=list)
    status: str | None = None
    limit: int = Field(default=40, ge=1, le=200)


@router.post("/matches/run")
async def run_matching(body: MatchIn) -> dict:
    return await _call(match_service.match_jobs, body.job_ids or None, body.status, body.limit)


@router.post("/matches/regroup")
async def regroup() -> list[dict]:
    return await _call(match_service.group_jobs)


@router.get("/matches")
def list_matches(min_score: float = 0) -> dict:
    p = prepo.get_current_profile()
    if not p:
        return {"profile_id": None, "matches": [], "groups": []}
    return {"profile_id": p["id"], "matches": crepo.list_matches(p["id"], min_score), "groups": crepo.list_groups(p["id"])}


# ── CV versions ────────────────────────────────────────────────────────────────

class ProposeIn(BaseModel):
    job_group_id: int | None = None
    job_id: int | None = None
    cv_id: int | None = None


@router.post("/cv-versions")
async def propose_cv(body: ProposeIn) -> dict:
    return await _call(cv_service.propose_changes, body.job_group_id, body.job_id, body.cv_id)


@router.get("/cv-versions")
def list_cv_versions() -> list[dict]:
    return crepo.list_versions()


@router.get("/cv-versions/{version_id}")
def get_cv_version(version_id: int) -> dict:
    return _not_found(crepo.get_version(version_id), "CV version")


class Decision(BaseModel):
    approve: bool


@router.post("/cv-proposals/{proposal_id}/decision")
async def decide_proposal(proposal_id: int, body: Decision) -> dict:
    return await _call(cv_service.decide, proposal_id, body.approve)


@router.post("/cv-versions/{version_id}/decide-all")
async def decide_all(version_id: int, body: Decision) -> dict:
    return {"updated": await _call(cv_service.decide_all, version_id, body.approve)}


@router.post("/cv-versions/{version_id}/generate")
async def generate_cv(version_id: int) -> dict:
    return await _call(cv_service.generate, version_id)


@router.get("/cv-versions/{version_id}/download/{kind}")
async def download_cv(version_id: int, kind: Literal["docx", "pdf"]):
    path = await _call(cv_service.output_file, version_id, kind)
    media = ("application/vnd.openxmlformats-officedocument.wordprocessingml.document" if kind == "docx"
             else "application/pdf")
    return FileResponse(path, media_type=media, filename=path.name)


@router.get("/cv-versions/{version_id}/preview")
async def preview_cv(version_id: int) -> dict:
    return await _call(cv_service.preview, version_id)


class CvDraftIn(BaseModel):
    structure: dict


@router.put("/cv-versions/{version_id}/draft")
async def save_cv_draft(version_id: int, body: CvDraftIn) -> dict:
    return await _call(cv_service.save_draft, version_id, body.structure)


@router.delete("/cv-versions/{version_id}/draft")
async def reset_cv_draft(version_id: int) -> dict:
    return await _call(cv_service.reset_draft, version_id)


@router.get("/cv-extras")
def get_cv_extras() -> dict:
    import cv_render

    return {**cv_render.load_extras(), "photo_saved": cv_render.current_photo() is not None}


@router.post("/cv-photo")
async def upload_cv_photo(file: UploadFile = File(...)) -> dict:
    import cv_render

    data = await file.read()
    try:
        target = cv_render.save_photo(data, file.filename or "")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    logger.info("cv photo saved: %s", target.name)
    return {"saved": target.name}


@router.delete("/cv-photo")
def remove_cv_photo() -> dict:
    import cv_render

    return {"removed": cv_render.delete_photo()}


class CvExtrasIn(BaseModel):
    contact: dict = Field(default_factory=dict)
    languages: list[dict] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)


@router.put("/cv-extras")
def save_cv_extras(body: CvExtrasIn) -> dict:
    import cv_render

    return cv_render.save_extras(body.model_dump())


@router.delete("/cv-versions/{version_id}")
def delete_cv_version(version_id: int) -> dict:
    _not_found(crepo.delete_version(version_id), "CV version")
    return {"deleted": version_id}


# ── Contacts ───────────────────────────────────────────────────────────────────

class ContactIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=300)
    title: str = Field(default="", max_length=300)
    company: str = Field(default="", max_length=300)
    email: str = Field(default="", max_length=320)
    linkedin_url: str = Field(default="", max_length=1000)
    role: Literal["recruiter", "hiring_manager", "careers_inbox", "other"] = "recruiter"


@router.get("/jobs/{job_id}/outreach")
async def job_outreach(job_id: int) -> dict:
    return await _call(outreach_service.action_card, job_id)


@router.post("/jobs/{job_id}/contacts")
async def add_contact(job_id: int, body: ContactIn) -> dict:
    return await _call(outreach_service.add_manual_contact, job_id, body.model_dump())


@router.post("/jobs/{job_id}/contacts/from-posting")
async def contacts_from_posting(job_id: int) -> list[dict]:
    return await _call(outreach_service.contacts_from_posting, job_id)


class ApolloSearchIn(BaseModel):
    titles: list[str] = Field(default_factory=list)


@router.post("/jobs/{job_id}/contacts/apollo-search")
async def apollo_search(job_id: int, body: ApolloSearchIn) -> dict:
    return await _call(outreach_service.apollo_search, job_id, body.titles or None)


class ApolloPersonIn(BaseModel):
    apollo_person_id: str
    full_name: str
    title: str = ""
    company: str = ""
    linkedin_url: str = ""
    email: str = ""
    email_status: str = "unknown"
    role: Literal["recruiter", "hiring_manager", "careers_inbox", "other"] = "recruiter"


@router.post("/jobs/{job_id}/contacts/apollo-save")
def apollo_save(job_id: int, body: ApolloPersonIn) -> dict:
    data = body.model_dump()
    role = data.pop("role")
    return outreach_service.save_apollo_contact(job_id, data, role)


@router.post("/contacts/{contact_id}/reveal-email")
async def reveal_email(contact_id: int) -> dict:
    return await _call(outreach_service.reveal_contact_email, contact_id)


@router.delete("/jobs/{job_id}/contacts/{contact_id}")
def unlink_contact(job_id: int, contact_id: int) -> dict:
    _not_found(orepo.unlink_contact(job_id, contact_id), "Contact link")
    return {"deleted": contact_id}


# ── Outreach threads and messages ──────────────────────────────────────────────

class DraftIn(BaseModel):
    job_id: int
    contact_id: int
    channel: Literal["email", "linkedin"]
    cv_version_id: int | None = None


@router.post("/outreach/drafts")
async def create_draft(body: DraftIn) -> dict:
    return await _call(outreach_service.create_draft, body.job_id, body.contact_id, body.channel, body.cv_version_id)


@router.get("/outreach/threads")
def list_threads(status: str | None = None, job_id: int | None = None) -> list[dict]:
    return orepo.list_threads(job_id=job_id, status=status)


@router.get("/outreach/threads/{thread_id}")
def get_thread(thread_id: int) -> dict:
    return _not_found(orepo.get_thread(thread_id), "Thread")


class ThreadStatusIn(BaseModel):
    status: Literal["sent", "replied", "waiting", "closed", "skipped"]


@router.delete("/outreach/threads/{thread_id}")
async def delete_outreach_thread(thread_id: int) -> dict:
    await _call(outreach_service.delete_thread, thread_id)
    return {"deleted": thread_id}


class RefineIn(BaseModel):
    instruction: str = Field(min_length=1, max_length=500)


@router.post("/outreach/messages/{message_id}/attach-cv")
async def attach_cv_to_draft(message_id: int) -> dict:
    return await _call(outreach_service.attach_cv, message_id)


@router.post("/outreach/messages/{message_id}/make-cv")
async def make_cv_for_draft(message_id: int) -> dict:
    return await _call(outreach_service.make_cv, message_id)


@router.post("/outreach/messages/{message_id}/refine")
async def refine_outreach_message(message_id: int, body: RefineIn) -> dict:
    return await _call(outreach_service.refine_draft, message_id, body.instruction)


@router.post("/outreach/threads/{thread_id}/status")
async def thread_status(thread_id: int, body: ThreadStatusIn) -> dict:
    return await _call(outreach_service.mark_thread, thread_id, body.status)


class LinkedinReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=10000)


@router.post("/outreach/threads/{thread_id}/linkedin-reply")
async def linkedin_reply(thread_id: int, body: LinkedinReplyIn) -> dict:
    return await _call(outreach_service.add_linkedin_reply, thread_id, body.text)


class ReplyDraftIn(BaseModel):
    guidance: str = Field(default="", max_length=2000)


@router.post("/outreach/threads/{thread_id}/draft-reply")
async def draft_reply(thread_id: int, body: ReplyDraftIn) -> dict:
    return await _call(outreach_service.draft_reply, thread_id, body.guidance)


class MessageEdit(BaseModel):
    subject: str | None = Field(default=None, max_length=500)
    body: str = Field(min_length=1, max_length=20000)
    attachments: list[str] | None = None


@router.put("/outreach/messages/{message_id}")
async def edit_message(message_id: int, body: MessageEdit) -> dict:
    return await _call(outreach_service.update_draft, message_id, body.subject, body.body, body.attachments)


@router.post("/outreach/messages/{message_id}/approve")
async def approve_message(message_id: int) -> dict:
    return await _call(outreach_service.approve, message_id)


class SendIn(BaseModel):
    confirm_duplicate: bool = False


@router.post("/outreach/messages/{message_id}/send")
async def send_message(message_id: int, body: SendIn) -> dict:
    return await _call(outreach_service.send, message_id, body.confirm_duplicate)


@router.get("/outreach/messages/{message_id}/gmail-compose-url")
async def gmail_compose(message_id: int) -> dict:
    return {"url": await _call(outreach_service.gmail_compose_url, message_id)}


@router.delete("/outreach/messages/{message_id}")
async def discard_message(message_id: int) -> dict:
    await _call(outreach_service.discard, message_id)
    return {"deleted": message_id}


@router.post("/outreach/check-replies")
async def check_replies() -> dict:
    return await _call(outreach_service.check_replies)


# ── Email account ──────────────────────────────────────────────────────────────

@router.get("/email/status")
def email_status() -> dict:
    return outreach_service.email_status()


@router.post("/email/connect/gmail")
async def connect_gmail() -> dict:
    return await _call(outreach_service.connect_gmail)


@router.post("/email/connect/smtp")
async def connect_smtp() -> dict:
    return await _call(outreach_service.connect_smtp)


@router.delete("/email/account")
def disconnect_email() -> dict:
    return {"disconnected": outreach_service.disconnect_email()}


# ── Availability ───────────────────────────────────────────────────────────────

class SlotIn(BaseModel):
    starts_at: datetime
    ends_at: datetime
    timezone: str = Field(default="Asia/Kolkata", max_length=60)


@router.get("/availability")
def list_slots() -> list[dict]:
    return orepo.list_slots(upcoming_only=False)


@router.post("/availability")
async def add_slot(body: SlotIn) -> dict:
    return await _call(outreach_service.add_slot, body.starts_at, body.ends_at, body.timezone)


@router.delete("/availability/{slot_id}")
def delete_slot(slot_id: int) -> dict:
    _not_found(orepo.delete_slot(slot_id), "Slot")
    return {"deleted": slot_id}


# ── Assistant ──────────────────────────────────────────────────────────────────

@router.post("/agent/chat")
async def agent_chat(body: ChatRequest) -> dict:
    return await _call(run_in_threadpool, agent.chat, body.session_id, body.message)


@router.get("/agent/sessions")
def agent_sessions() -> list[dict]:
    return repo.list_assistant_sessions()


@router.get("/agent/sessions/{session_id}/messages")
def agent_session_messages(session_id: str) -> list[dict]:
    return repo.list_assistant_messages(session_id)


@router.post("/agent/reset")
def agent_reset(body: ChatRequest) -> dict:
    agent.reset(body.session_id)
    return {"reset": body.session_id}
