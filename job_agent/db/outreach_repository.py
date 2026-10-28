"""Data access for contacts, email account, outreach threads and messages, availability."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select

from db.models import (
    AvailabilitySlot,
    Contact,
    EmailAccount,
    Job,
    JobContact,
    OutreachMessage,
    OutreachThread,
)
from db.repositories import _row
from db.session import session_scope
from utils import to_json, utcnow

# ── Contacts ───────────────────────────────────────────────────────────────────


def add_contact(job_id: int, data: dict, role: str) -> dict:
    """Create or reuse a contact (matched by email, Apollo ID, or LinkedIn URL) and link it to the job."""
    with session_scope() as s:
        c = None
        for field in ("email", "apollo_person_id", "linkedin_url"):
            value = data.get(field)
            if value:
                c = s.scalar(select(Contact).where(getattr(Contact, field) == value).limit(1))
                if c:
                    break
        if not c:
            c = Contact(full_name=data.get("full_name") or data.get("email") or "Unknown",
                        source=data.get("source") or "manual")
            s.add(c)
        for field in ("full_name", "title", "company", "email", "email_status", "linkedin_url", "source_ref",
                      "apollo_person_id"):
            if data.get(field):
                setattr(c, field, data[field])
        s.flush()
        link = s.scalar(select(JobContact).where(JobContact.job_id == job_id, JobContact.contact_id == c.id))
        if not link:
            s.add(JobContact(job_id=job_id, contact_id=c.id, role=role))
        return _row(c)


def get_contact(contact_id: int) -> dict | None:
    with session_scope() as s:
        c = s.get(Contact, contact_id)
        return _row(c) if c else None


def update_contact(contact_id: int, data: dict) -> dict | None:
    with session_scope() as s:
        c = s.get(Contact, contact_id)
        if not c:
            return None
        for k, v in data.items():
            if v is not None and hasattr(c, k):
                setattr(c, k, v)
        s.flush()
        return _row(c)


def job_contacts(job_id: int) -> list[dict]:
    with session_scope() as s:
        rows = s.execute(select(Contact, JobContact.role).join(JobContact, JobContact.contact_id == Contact.id)
                         .where(JobContact.job_id == job_id)).all()
        return [{**_row(c), "role": role} for c, role in rows]


def unlink_contact(job_id: int, contact_id: int) -> bool:
    with session_scope() as s:
        link = s.scalar(select(JobContact).where(JobContact.job_id == job_id, JobContact.contact_id == contact_id))
        if not link:
            return False
        s.delete(link)
        return True


# ── Email account ──────────────────────────────────────────────────────────────

def save_email_account(email_address: str, provider: str, encrypted_token: str | None, scopes: str, cap: int) -> dict:
    with session_scope() as s:
        for other in s.scalars(select(EmailAccount)).all():
            if other.email_address != email_address:
                s.delete(other)       # single-user app: one connected mailbox
        a = s.scalar(select(EmailAccount).where(EmailAccount.email_address == email_address))
        if not a:
            a = EmailAccount(email_address=email_address, provider=provider)
            s.add(a)
        a.provider, a.encrypted_token, a.scopes, a.connected_at, a.daily_send_cap = (
            provider, encrypted_token, scopes, utcnow(), cap)
        s.flush()
        d = _row(a)
        d.pop("encrypted_token", None)
        return d


def get_email_account(include_token: bool = False) -> dict | None:
    with session_scope() as s:
        a = s.scalar(select(EmailAccount).limit(1))
        if not a:
            return None
        d = _row(a)
        if not include_token:
            d.pop("encrypted_token", None)
        return d


def update_email_token(encrypted_token: str) -> None:
    with session_scope() as s:
        a = s.scalar(select(EmailAccount).limit(1))
        if a:
            a.encrypted_token = encrypted_token


def delete_email_account() -> bool:
    with session_scope() as s:
        rows = s.scalars(select(EmailAccount)).all()
        for a in rows:
            s.delete(a)
        return bool(rows)


# ── Threads and messages ───────────────────────────────────────────────────────

def create_thread(job_id: int, contact_id: int, channel: str, cv_version_id: int | None) -> int:
    with session_scope() as s:
        t = OutreachThread(job_id=job_id, contact_id=contact_id, channel=channel, cv_version_id=cv_version_id,
                           status="draft", last_activity_at=utcnow())
        s.add(t)
        s.flush()
        return t.id


def add_message(thread_id: int, direction: str, body: str, status: str, **fields) -> dict:
    with session_scope() as s:
        m = OutreachMessage(thread_id=thread_id, direction=direction, body=body, status=status,
                            subject=fields.get("subject"),
                            attachment_paths_json=to_json(fields.get("attachments") or []),
                            gmail_message_id=fields.get("gmail_message_id"),
                            rfc822_message_id=fields.get("rfc822_message_id"),
                            in_reply_to=fields.get("in_reply_to"), received_at=fields.get("received_at"),
                            reply_category=fields.get("reply_category"), drafted_by=fields.get("drafted_by", "agent"))
        s.add(m)
        t = s.get(OutreachThread, thread_id)
        if t:
            t.last_activity_at = utcnow()
        s.flush()
        return _row(m, json_fields=("attachment_paths_json",))


def get_message(message_id: int) -> dict | None:
    with session_scope() as s:
        m = s.get(OutreachMessage, message_id)
        return _row(m, json_fields=("attachment_paths_json",)) if m else None


def update_message(message_id: int, **fields) -> dict | None:
    with session_scope() as s:
        m = s.get(OutreachMessage, message_id)
        if not m:
            return None
        for k, v in fields.items():
            if k == "attachments":
                m.attachment_paths_json = to_json(v or [])
            elif hasattr(m, k):
                setattr(m, k, v)
        s.flush()
        return _row(m, json_fields=("attachment_paths_json",))


def delete_message(message_id: int) -> bool:
    with session_scope() as s:
        m = s.get(OutreachMessage, message_id)
        if not m:
            return False
        s.delete(m)
        return True


def set_thread(thread_id: int, **fields) -> None:
    with session_scope() as s:
        t = s.get(OutreachThread, thread_id)
        if t:
            for k, v in fields.items():
                setattr(t, k, v)
            t.last_activity_at = utcnow()


def get_thread(thread_id: int) -> dict | None:
    with session_scope() as s:
        t = s.get(OutreachThread, thread_id)
        if not t:
            return None
        d = _row(t)
        c = s.get(Contact, t.contact_id)
        j = s.get(Job, t.job_id)
        d["contact"] = _row(c) if c else None
        d["job"] = ({"id": j.id, "title": j.title, "company": j.company, "apply_url": j.apply_url,
                     "description": j.description, "location": j.location} if j else None)
        d["messages"] = [_row(m, json_fields=("attachment_paths_json",)) for m in s.scalars(
            select(OutreachMessage).where(OutreachMessage.thread_id == thread_id).order_by(OutreachMessage.id)).all()]
        return d


def list_threads(job_id: int | None = None, status: str | None = None) -> list[dict]:
    with session_scope() as s:
        stmt = select(OutreachThread.id).order_by(OutreachThread.last_activity_at.desc())
        if job_id:
            stmt = stmt.where(OutreachThread.job_id == job_id)
        if status:
            stmt = stmt.where(OutreachThread.status == status)
        ids = list(s.scalars(stmt).all())
    out = []
    for tid in ids:
        t = get_thread(tid)
        if t:
            t["job"] = {k: v for k, v in (t["job"] or {}).items() if k != "description"}
            out.append(t)
    return out


def tracked_gmail_threads() -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(select(OutreachThread).where(OutreachThread.gmail_thread_id.is_not(None),
                                                      OutreachThread.status.not_in(("closed", "skipped")))).all()
        return [_row(t) for t in rows]


def known_gmail_message_ids(thread_id: int) -> set[str]:
    with session_scope() as s:
        return {x for x in s.scalars(select(OutreachMessage.gmail_message_id).where(
            OutreachMessage.thread_id == thread_id, OutreachMessage.gmail_message_id.is_not(None))).all()}


def known_rfc822_ids() -> set[str]:
    with session_scope() as s:
        return {x for x in s.scalars(select(OutreachMessage.rfc822_message_id).where(
            OutreachMessage.rfc822_message_id.is_not(None))).all()}


def outbound_sent_smtp() -> list[dict]:
    """Sent outbound messages with no Gmail thread (SMTP path), for IMAP reply matching."""
    with session_scope() as s:
        rows = s.execute(select(OutreachMessage, OutreachThread)
                         .join(OutreachThread, OutreachThread.id == OutreachMessage.thread_id)
                         .where(OutreachMessage.direction == "outbound", OutreachMessage.status == "sent",
                                OutreachMessage.rfc822_message_id.is_not(None),
                                OutreachThread.gmail_thread_id.is_(None),
                                OutreachThread.status.not_in(("closed", "skipped")))).all()
        return [{"thread_id": t.id, "rfc822_message_id": m.rfc822_message_id} for m, t in rows]


def sent_count_since(since: datetime) -> int:
    with session_scope() as s:
        return s.scalar(select(func.count(OutreachMessage.id)).where(
            OutreachMessage.direction == "outbound", OutreachMessage.status == "sent",
            OutreachMessage.sent_at >= since)) or 0


def sent_today() -> int:
    now = utcnow()
    return sent_count_since(now - timedelta(hours=24))


def already_emailed(job_id: int, contact_id: int, exclude_thread_id: int) -> bool:
    with session_scope() as s:
        return bool(s.scalar(select(OutreachMessage.id).join(OutreachThread, OutreachThread.id == OutreachMessage.thread_id)
                             .where(OutreachThread.job_id == job_id, OutreachThread.contact_id == contact_id,
                                    OutreachThread.id != exclude_thread_id, OutreachThread.channel == "email",
                                    OutreachMessage.direction == "outbound", OutreachMessage.status == "sent").limit(1)))


# ── Availability ───────────────────────────────────────────────────────────────

def add_slot(starts_at: datetime, ends_at: datetime, tz: str) -> dict:
    with session_scope() as s:
        a = AvailabilitySlot(starts_at=starts_at, ends_at=ends_at, timezone=tz)
        s.add(a)
        s.flush()
        return _row(a)


def list_slots(upcoming_only: bool = True) -> list[dict]:
    """Slots are stored in the local time you entered (label in `timezone`), so compare with local time."""
    with session_scope() as s:
        stmt = select(AvailabilitySlot).order_by(AvailabilitySlot.starts_at)
        if upcoming_only:
            stmt = stmt.where(AvailabilitySlot.ends_at >= datetime.now())
        return [_row(a) for a in s.scalars(stmt).all()]


def delete_slot(slot_id: int) -> bool:
    with session_scope() as s:
        a = s.get(AvailabilitySlot, slot_id)
        if not a:
            return False
        s.delete(a)
        return True


def delete_thread(thread_id: int) -> bool:
    """Delete a thread and its messages (local only)."""
    from sqlalchemy import delete as sql_delete

    with session_scope() as s:
        t = s.get(OutreachThread, thread_id)
        if not t:
            return False
        s.execute(sql_delete(OutreachMessage).where(OutreachMessage.thread_id == thread_id))
        s.delete(t)
        return True
