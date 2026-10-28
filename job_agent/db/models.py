"""SQLAlchemy models. These are the schema source of truth; Alembic follows them.

Every table in README section 9 is defined here, including those used by later
phases, so later phases add behaviour rather than new foundations.
JSON values are stored as TEXT (columns ending in _json). Timestamps are naive UTC.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from utils import utcnow


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow, nullable=False)


# ── Profile ────────────────────────────────────────────────────────────────────

class CvDocument(TimestampMixin, Base):
    __tablename__ = "cv_documents"
    file_name: Mapped[str] = mapped_column(String(300))
    file_path: Mapped[str] = mapped_column(String(1000))
    file_type: Mapped[str] = mapped_column(String(10))            # pdf | docx
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    structure_json: Mapped[str | None] = mapped_column(Text)      # sections and bullets, used for tailoring
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)


class CvNote(TimestampMixin, Base):
    __tablename__ = "cv_notes"
    cv_document_id: Mapped[int] = mapped_column(ForeignKey("cv_documents.id", ondelete="CASCADE"), index=True)
    note: Mapped[str] = mapped_column(Text)


class LinkedinSource(TimestampMixin, Base):
    __tablename__ = "linkedin_sources"
    source_type: Mapped[str] = mapped_column(String(20))          # apify | export_csv | pdf
    file_path: Mapped[str | None] = mapped_column(String(1000))
    raw_json: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime | None] = mapped_column()


class GithubAccount(TimestampMixin, Base):
    __tablename__ = "github_accounts"
    __table_args__ = (UniqueConstraint("account_type", "login_or_org", name="uq_github_account"),)
    account_type: Mapped[str] = mapped_column(String(20))         # personal | company
    login_or_org: Mapped[str] = mapped_column(String(200))
    last_synced_at: Mapped[datetime | None] = mapped_column()


class GithubRepo(TimestampMixin, Base):
    __tablename__ = "github_repos"
    __table_args__ = (UniqueConstraint("github_account_id", "full_name", name="uq_github_repo"),)
    github_account_id: Mapped[int] = mapped_column(ForeignKey("github_accounts.id", ondelete="CASCADE"), index=True)
    full_name: Mapped[str] = mapped_column(String(300))
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    primary_language: Mapped[str | None] = mapped_column(String(100))
    topics_json: Mapped[str | None] = mapped_column(Text)
    last_pushed_at: Mapped[datetime | None] = mapped_column()
    my_commit_count: Mapped[int | None] = mapped_column(Integer)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    llm_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    readme_text: Mapped[str | None] = mapped_column(Text)


class ManualProject(TimestampMixin, Base):
    __tablename__ = "manual_projects"
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    tech_json: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(1000))


class Profile(TimestampMixin, Base):
    __tablename__ = "profiles"
    version: Mapped[int] = mapped_column(Integer)
    profile_json: Mapped[str] = mapped_column(Text)
    source_ids_json: Mapped[str | None] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class TargetRole(TimestampMixin, Base):
    __tablename__ = "target_roles"
    title: Mapped[str] = mapped_column(String(200))
    seniority: Mapped[str | None] = mapped_column(String(50))
    locations_json: Mapped[str | None] = mapped_column(Text)
    remote_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    onet_codes_json: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="confirmed")   # proposed | confirmed | rejected


# ── Jobs ───────────────────────────────────────────────────────────────────────

class JobSearch(TimestampMixin, Base):
    __tablename__ = "job_searches"
    target_role_id: Mapped[int | None] = mapped_column(ForeignKey("target_roles.id", ondelete="SET NULL"), index=True)
    query: Mapped[str] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str | None] = mapped_column(String(60))
    sources_json: Mapped[str] = mapped_column(Text)
    request_json: Mapped[str | None] = mapped_column(Text)
    results_summary_json: Mapped[str | None] = mapped_column(Text)   # per-source status and counts
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | completed | failed
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column()


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"
    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str | None] = mapped_column(String(300), index=True)
    company_domain: Mapped[str | None] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column()
    posted_text: Mapped[str | None] = mapped_column(String(100))
    apply_url: Mapped[str | None] = mapped_column(String(2000))
    salary_text: Mapped[str | None] = mapped_column(String(200))
    employment_type: Mapped[str | None] = mapped_column(String(100))
    dedupe_key: Mapped[str] = mapped_column(String(800), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)


class JobSourceRecord(TimestampMixin, Base):
    __tablename__ = "job_source_records"
    __table_args__ = (UniqueConstraint("source", "source_job_id", name="uq_job_source_record"),)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    job_search_id: Mapped[int | None] = mapped_column(ForeignKey("job_searches.id", ondelete="SET NULL"), index=True)
    source: Mapped[str] = mapped_column(String(30))       # predictleads | serpapi | adzuna | ats | guidance
    source_job_id: Mapped[str] = mapped_column(String(500))
    source_url: Mapped[str | None] = mapped_column(String(2000))
    via: Mapped[str | None] = mapped_column(String(200))  # portal the posting came through, e.g. Naukri
    raw_json: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(default=utcnow)


class JobRef(TimestampMixin, Base):
    """Identifiers of one posting seen across sources (ATS job id, Naukri id, cleaned apply URL).
    A new record sharing any ref with a stored job is merged into it."""
    __tablename__ = "job_refs"
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    ref: Mapped[str] = mapped_column(String(800), unique=True)


class GuidanceUrl(TimestampMixin, Base):
    __tablename__ = "guidance_urls"
    url: Mapped[str] = mapped_column(String(2000), unique=True)
    portal: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str | None] = mapped_column(String(300))
    company: Mapped[str | None] = mapped_column(String(300))
    location: Mapped[str | None] = mapped_column(String(300))
    pasted_description: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True)


class AtsBoard(TimestampMixin, Base):
    __tablename__ = "ats_boards"
    __table_args__ = (UniqueConstraint("provider", "board_token", name="uq_ats_board"),)
    provider: Mapped[str] = mapped_column(String(20))        # greenhouse | lever | ashby
    board_token: Mapped[str] = mapped_column(String(200))
    company_name: Mapped[str | None] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column()


class JobGroup(TimestampMixin, Base):
    __tablename__ = "job_groups"
    name: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text)
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("profiles.id", ondelete="SET NULL"), index=True)


class JobMatch(TimestampMixin, Base):
    __tablename__ = "job_matches"
    __table_args__ = (UniqueConstraint("job_id", "profile_id", name="uq_job_match"),)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    score: Mapped[float] = mapped_column(Float)
    gaps_json: Mapped[str | None] = mapped_column(Text)
    reasons_json: Mapped[str | None] = mapped_column(Text)
    job_group_id: Mapped[int | None] = mapped_column(ForeignKey("job_groups.id", ondelete="SET NULL"), index=True)


# ── CV versions ────────────────────────────────────────────────────────────────

class CvVersion(TimestampMixin, Base):
    __tablename__ = "cv_versions"
    base_cv_document_id: Mapped[int] = mapped_column(ForeignKey("cv_documents.id", ondelete="CASCADE"), index=True)
    job_group_id: Mapped[int | None] = mapped_column(ForeignKey("job_groups.id", ondelete="SET NULL"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")      # draft | approved | generated
    draft_json: Mapped[str | None] = mapped_column(Text)                # your edits in the preview (whole CV)
    docx_path: Mapped[str | None] = mapped_column(String(1000))
    pdf_path: Mapped[str | None] = mapped_column(String(1000))
    generated_at: Mapped[datetime | None] = mapped_column()


class CvChangeProposal(TimestampMixin, Base):
    __tablename__ = "cv_change_proposals"
    cv_version_id: Mapped[int] = mapped_column(ForeignKey("cv_versions.id", ondelete="CASCADE"), index=True)
    section: Mapped[str] = mapped_column(String(200))
    change_type: Mapped[str] = mapped_column(String(30))   # reword | reorder | promote_skill | drop | add_project
    original_text: Mapped[str | None] = mapped_column(Text)
    proposed_text: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    evidence_json: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="proposed")  # proposed | approved | rejected
    decided_at: Mapped[datetime | None] = mapped_column()


# ── Outreach and email ─────────────────────────────────────────────────────────

class Contact(TimestampMixin, Base):
    __tablename__ = "contacts"
    full_name: Mapped[str] = mapped_column(String(300))
    title: Mapped[str | None] = mapped_column(String(300))
    company: Mapped[str | None] = mapped_column(String(300))
    email: Mapped[str | None] = mapped_column(String(320), index=True)
    email_status: Mapped[str] = mapped_column(String(20), default="unknown")   # verified | guessed | unknown
    linkedin_url: Mapped[str | None] = mapped_column(String(1000))
    source: Mapped[str] = mapped_column(String(20))      # posting | manual | careers_page | apollo
    source_ref: Mapped[str | None] = mapped_column(String(1000))
    apollo_person_id: Mapped[str | None] = mapped_column(String(100))


class JobContact(TimestampMixin, Base):
    __tablename__ = "job_contacts"
    __table_args__ = (UniqueConstraint("job_id", "contact_id", name="uq_job_contact"),)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(30))        # recruiter | hiring_manager | careers_inbox | other


class EmailAccount(TimestampMixin, Base):
    __tablename__ = "email_accounts"
    email_address: Mapped[str] = mapped_column(String(320), unique=True)
    provider: Mapped[str] = mapped_column(String(20))    # gmail_api | smtp
    encrypted_token: Mapped[str | None] = mapped_column(Text)
    scopes: Mapped[str | None] = mapped_column(Text)
    connected_at: Mapped[datetime | None] = mapped_column()
    daily_send_cap: Mapped[int] = mapped_column(Integer, default=20)


class OutreachThread(TimestampMixin, Base):
    __tablename__ = "outreach_threads"
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(20))     # email | linkedin
    cv_version_id: Mapped[int | None] = mapped_column(ForeignKey("cv_versions.id", ondelete="SET NULL"))
    gmail_thread_id: Mapped[str | None] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | sent | replied | waiting | closed | skipped
    last_activity_at: Mapped[datetime | None] = mapped_column()


class OutreachMessage(TimestampMixin, Base):
    __tablename__ = "outreach_messages"
    thread_id: Mapped[int] = mapped_column(ForeignKey("outreach_threads.id", ondelete="CASCADE"), index=True)
    direction: Mapped[str] = mapped_column(String(10))   # outbound | inbound
    subject: Mapped[str | None] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    attachment_paths_json: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))      # draft | approved | sent | failed | received
    gmail_message_id: Mapped[str | None] = mapped_column(String(100), index=True)
    rfc822_message_id: Mapped[str | None] = mapped_column(String(500))
    in_reply_to: Mapped[str | None] = mapped_column(String(500))
    approved_at: Mapped[datetime | None] = mapped_column()
    sent_at: Mapped[datetime | None] = mapped_column(index=True)
    received_at: Mapped[datetime | None] = mapped_column()
    reply_category: Mapped[str | None] = mapped_column(String(30))
    drafted_by: Mapped[str] = mapped_column(String(10), default="agent")   # agent | user


class AvailabilitySlot(TimestampMixin, Base):
    __tablename__ = "availability_slots"
    starts_at: Mapped[datetime] = mapped_column()
    ends_at: Mapped[datetime] = mapped_column()
    timezone: Mapped[str] = mapped_column(String(60), default="Asia/Kolkata")


# ── Tracking ───────────────────────────────────────────────────────────────────

class ApiUsage(TimestampMixin, Base):
    __tablename__ = "api_usage"
    source: Mapped[str] = mapped_column(String(30), index=True)
    endpoint: Mapped[str] = mapped_column(String(200))
    credits_used: Mapped[float] = mapped_column(Float, default=0)
    status_code: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(String(500))
    called_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    job_search_id: Mapped[int | None] = mapped_column(ForeignKey("job_searches.id", ondelete="SET NULL"))


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_log"
    action: Mapped[str] = mapped_column(String(50), index=True)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    details_json: Mapped[str | None] = mapped_column(Text)


class AssistantMessage(TimestampMixin, Base):
    """One message of an Assistant chat. Kept so past conversations survive a restart."""
    __tablename__ = "assistant_messages"
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(10))           # user | assistant
    content: Mapped[str] = mapped_column(Text)
    tools_json: Mapped[str | None] = mapped_column(Text)
