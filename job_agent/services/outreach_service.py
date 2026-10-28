"""Outreach: contacts, drafts, approval, one-at-a-time sending from your personal Gmail,
reply checking on tracked threads only, and next-reply drafts.

Rules enforced here (README section 9):
- A message can be sent only from status 'approved'. Editing resets it to 'draft'.
- One email per call. Daily cap from EMAIL_DAILY_SEND_CAP.
- The same contact is not emailed twice for the same job unless confirm_duplicate is true.
- LinkedIn messages are never sent by the app.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

import llm
from clients import apollo, gmail, smtp_mail
from config import OUTPUTS_DIR, settings
from db import cv_repository as crepo
from db import outreach_repository as orepo
from db import profile_repository as prepo
from db import repositories as repo
from services.profile_service import _run_llm
from utils import decrypt_secret, encrypt_secret, logger, safe_error, to_json, utcnow

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


# ── Contacts ───────────────────────────────────────────────────────────────────

def add_manual_contact(job_id: int, data: dict) -> dict:
    if not repo.get_job(job_id):
        raise LookupError("Job not found")
    if not (data.get("email") or data.get("linkedin_url")):
        raise ValueError("Give an email or a LinkedIn profile URL")
    return orepo.add_contact(job_id, {**data, "source": "manual",
                                      "email_status": "verified" if data.get("email") else "unknown"},
                             data.get("role") or "recruiter")


def contacts_from_posting(job_id: int) -> list[dict]:
    """Pick up email addresses written in the job description (no network call)."""
    job = repo.get_job(job_id)
    if not job:
        raise LookupError("Job not found")
    found = []
    for email in sorted(set(EMAIL_RE.findall(job.get("description") or ""))):
        if email.lower().endswith((".png", ".jpg", ".gif")):
            continue
        local = email.split("@")[0].lower()
        role = "careers_inbox" if any(k in local for k in ("career", "jobs", "hr", "hiring", "talent", "recruit")) else "recruiter"
        found.append(orepo.add_contact(job_id, {"full_name": email, "email": email, "company": job.get("company"),
                                                "source": "posting", "email_status": "guessed",
                                                "source_ref": job.get("apply_url")}, role))
    return found


async def apollo_search(job_id: int, titles: list[str] | None = None) -> dict:
    job = repo.get_job(job_id)
    if not job:
        raise LookupError("Job not found")
    res = await apollo.search_people(job.get("company_domain") or "", job.get("company") or "", titles)
    repo.record_usage("apollo", "mixed_people/api_search", 0, None, res.get("error", ""))
    if "error" in res:
        raise ValueError(res["error"])
    return {"job_id": job_id, "people": res["people"]}


def save_apollo_contact(job_id: int, person: dict, role: str = "recruiter") -> dict:
    return orepo.add_contact(job_id, {**person, "source": "apollo"}, role)


async def reveal_contact_email(contact_id: int) -> dict:
    """Spends Apollo credits. Called only from the UI button, never by the agent."""
    c = orepo.get_contact(contact_id)
    if not c:
        raise LookupError("Contact not found")
    if not c.get("apollo_person_id"):
        raise ValueError("This contact did not come from Apollo")
    res = await apollo.reveal_email(c["apollo_person_id"])
    repo.record_usage("apollo", "people/match", 1 if "person" in res else 0, None, res.get("error", ""))
    if "error" in res:
        raise ValueError(res["error"])
    p = res["person"]
    repo.add_audit("reveal_email", "contact", contact_id)
    return orepo.update_contact(contact_id, {"email": p.get("email") or None,
                                             "email_status": p.get("email_status") or "unknown",
                                             "linkedin_url": p.get("linkedin_url") or None})


def action_card(job_id: int) -> dict:
    """Recommended channel per contact, plus the CV to use."""
    job = repo.get_job(job_id)
    if not job:
        raise LookupError("Job not found")
    contacts = orepo.job_contacts(job_id)
    cv = crepo.version_for_job(job_id)
    cards = []
    for c in contacts:
        channels = (["email"] if c.get("email") else []) + (["linkedin"] if c.get("linkedin_url") else [])
        cards.append({"contact": c, "recommended": channels[0] if channels else "apply_only", "channels": channels})
    return {"job": {k: job[k] for k in ("id", "title", "company", "apply_url", "status")},
            "cv_version": ({"id": cv["id"], "pdf_path": cv.get("pdf_path"), "docx_path": cv.get("docx_path")}
                           if cv else None),
            "contacts": cards,
            "message": "" if cards else "No contact found. Apply directly, or find a contact.",
            "threads": orepo.list_threads(job_id=job_id)}


# ── Drafting ───────────────────────────────────────────────────────────────────

class EmailDraft(BaseModel):
    subject: str
    body: str


class LinkedInDraft(BaseModel):
    connection_note: str = Field(description="At most 280 characters")
    message: str = Field(description="Direct message, at most 900 characters")


OUTREACH_SYSTEM = (
    "You write short, specific job outreach for the candidate, in their voice, first person. Mention the exact role, "
    "one or two concrete matching facts (projects, skills, results) from the profile, and a clear ask. "
    "No flattery, no buzzwords, no placeholders like [Name] unless a value is unknown. Sign with the candidate's name. "
    + llm.FACTS_RULE
)


def _context(job: dict, contact: dict) -> str:
    profile = prepo.get_current_profile()
    if not profile:
        raise ValueError("Build your profile first")
    return (f"Candidate profile:\n{to_json(profile['profile'])}\n\nJob: {job['title']} at {job.get('company')}\n"
            f"Location: {job.get('location')}\nApply link: {job.get('apply_url')}\n"
            f"Description:\n{(job.get('description') or '')[:3000]}\n\n"
            f"Recipient: {contact.get('full_name')} ({contact.get('title') or 'unknown title'}) at {contact.get('company')}")


async def create_draft(job_id: int, contact_id: int, channel: Literal["email", "linkedin"],
                       cv_version_id: int | None = None) -> dict:
    job, contact = repo.get_job(job_id), orepo.get_contact(contact_id)
    if not job or not contact:
        raise LookupError("Job or contact not found")
    if channel == "email" and not contact.get("email"):
        raise ValueError("This contact has no email. Reveal it, add it, or use LinkedIn.")
    cv = crepo.get_version(cv_version_id) if cv_version_id else crepo.version_for_job(job_id)
    attachments = [cv["pdf_path"]] if cv and cv.get("pdf_path") else []
    ctx = _context(job, contact)
    thread_id = orepo.create_thread(job_id, contact_id, channel, cv["id"] if cv else None)
    if channel == "email":
        cv_line = ("A tailored CV (PDF) is attached; you may say so." if attachments else
                   "No CV is attached to this email; do not mention an attachment.")
        d = await _run_llm(EmailDraft, OUTREACH_SYSTEM,
                           ctx + f"\n\nWrite a cold email under 150 words. {cv_line}")
        orepo.add_message(thread_id, "outbound", d.body, "draft", subject=d.subject, attachments=attachments)
    else:
        d = await _run_llm(LinkedInDraft, OUTREACH_SYSTEM, ctx + "\n\nWrite a LinkedIn connection note and a DM.")
        orepo.add_message(thread_id, "outbound", d.message, "draft", subject=d.connection_note[:300])
    return orepo.get_thread(thread_id)


def update_draft(message_id: int, subject: str | None, body: str, attachments: list[str] | None) -> dict:
    m = orepo.get_message(message_id)
    if not m:
        raise LookupError("Message not found")
    if m["direction"] != "outbound" or m["status"] not in ("draft", "approved", "failed"):
        raise ValueError("Only unsent drafts can be edited")
    if attachments is not None:
        attachments = [str(_safe_attachment(a)) for a in attachments]
    # Any edit, including one to an approved draft, resets approval.
    return orepo.update_message(message_id, subject=subject, body=body, drafted_by="user", status="draft",
                                approved_at=None,
                                **({"attachments": attachments} if attachments is not None else {}))


def _safe_attachment(path: str) -> Path:
    p = Path(path).resolve()
    if OUTPUTS_DIR.resolve() not in p.parents or not p.is_file():
        raise ValueError("Attachments must be generated CV files from the outputs folder")
    return p


def approve(message_id: int) -> dict:
    m = orepo.get_message(message_id)
    if not m:
        raise LookupError("Message not found")
    if m["direction"] != "outbound" or m["status"] not in ("draft", "failed"):
        raise ValueError(f"A message in status '{m['status']}' cannot be approved")
    repo.add_audit("approve_message", "outreach_message", message_id)
    return orepo.update_message(message_id, status="approved", approved_at=utcnow())


def discard(message_id: int) -> bool:
    m = orepo.get_message(message_id)
    if not m or m["status"] == "sent" or m["direction"] != "outbound":
        raise ValueError("Only unsent drafts can be discarded")
    return orepo.delete_message(message_id)


def gmail_compose_url(message_id: int) -> str:
    m = orepo.get_message(message_id)
    if not m:
        raise LookupError("Message not found")
    t = orepo.get_thread(m["thread_id"])
    to = (t["contact"] or {}).get("email") or ""
    return ("https://mail.google.com/mail/?view=cm&fs=1&to=" + quote(to) + "&su=" + quote(m.get("subject") or "")
            + "&body=" + quote(m["body"]))


# ── Gmail account ──────────────────────────────────────────────────────────────

async def connect_gmail() -> dict:
    if not settings.ENCRYPTION_KEY:
        raise ValueError("ENCRYPTION_KEY is missing in job_agent/.env")
    token_json = await run_in_threadpool(gmail.run_oauth_flow)
    creds, _ = gmail.load_credentials(token_json)
    address = await run_in_threadpool(gmail.account_email, creds)
    if settings.GMAIL_ADDRESS and address.lower() != settings.GMAIL_ADDRESS.lower():
        raise ValueError(f"You signed in as {address}, but GMAIL_ADDRESS is {settings.GMAIL_ADDRESS}")
    acct = orepo.save_email_account(address, "gmail_api", encrypt_secret(token_json), " ".join(gmail.SCOPES),
                                    settings.EMAIL_DAILY_SEND_CAP)
    repo.add_audit("connect_gmail", "email_account", acct["id"], {"email": address})
    return acct


def connect_smtp() -> dict:
    if not smtp_mail.configured():
        raise ValueError("Set SMTP_USERNAME and SMTP_APP_PASSWORD in job_agent/.env")
    acct = orepo.save_email_account(settings.SMTP_USERNAME, "smtp", None, "smtp+imap", settings.EMAIL_DAILY_SEND_CAP)
    repo.add_audit("connect_smtp", "email_account", acct["id"])
    return acct


def disconnect_email() -> bool:
    repo.add_audit("disconnect_email", "email_account", None)
    return orepo.delete_email_account()


def email_status() -> dict:
    acct = orepo.get_email_account()
    return {"account": acct, "sent_last_24h": orepo.sent_today(),
            "daily_cap": (acct or {}).get("daily_send_cap") or settings.EMAIL_DAILY_SEND_CAP,
            "gmail_client_file_ready": gmail.client_file_ready(), "smtp_configured": smtp_mail.configured()}


def _gmail_creds():
    acct = orepo.get_email_account(include_token=True)
    if not acct or acct["provider"] != "gmail_api" or not acct.get("encrypted_token"):
        raise ValueError("Connect your Gmail first")
    creds, refreshed = gmail.load_credentials(decrypt_secret(acct["encrypted_token"]))
    if refreshed:
        orepo.update_email_token(encrypt_secret(refreshed))
    return creds, acct


# ── Sending ────────────────────────────────────────────────────────────────────

async def send(message_id: int, confirm_duplicate: bool = False) -> dict:
    m = orepo.get_message(message_id)
    if not m:
        raise LookupError("Message not found")
    if m["direction"] != "outbound" or m["status"] != "approved":
        raise ValueError("Approve this message before sending")
    t = orepo.get_thread(m["thread_id"])
    if t["channel"] != "email":
        raise ValueError("LinkedIn messages are sent by you on LinkedIn. Copy the text and mark it sent.")
    to = (t["contact"] or {}).get("email")
    if not to:
        raise ValueError("Contact has no email address")
    acct = orepo.get_email_account()
    if not acct:
        raise ValueError("Connect your personal Gmail first")
    cap = acct.get("daily_send_cap") or settings.EMAIL_DAILY_SEND_CAP
    if orepo.sent_today() >= cap:
        raise ValueError(f"Daily send cap of {cap} reached. Try again tomorrow.")
    first_message = not any(x["status"] == "sent" and x["direction"] == "outbound" for x in t["messages"])
    if first_message and not confirm_duplicate and orepo.already_emailed(t["job_id"], t["contact_id"], t["id"]):
        raise ValueError("You already emailed this contact about this job. Confirm to send again.")

    last_inbound = next((x for x in reversed(t["messages"]) if x["direction"] == "inbound"), None)
    in_reply_to = (last_inbound or {}).get("rfc822_message_id") or None
    refs = " ".join(x["rfc822_message_id"] for x in t["messages"] if x.get("rfc822_message_id")) or None
    subject = m.get("subject") or f"{t['job']['title']} role"
    if in_reply_to and not subject.lower().startswith("re:"):
        subject = "Re: " + subject
    attachments = [str(_safe_attachment(a)) for a in (m.get("attachment_paths") or [])]
    msg = gmail.build_message(acct["email_address"], to, subject, m["body"], attachments, in_reply_to, refs)
    try:
        if acct["provider"] == "gmail_api":
            creds, _ = _gmail_creds()
            res = await run_in_threadpool(gmail.send, creds, msg, t.get("gmail_thread_id"))
        else:
            res = await run_in_threadpool(smtp_mail.send, msg)
    except Exception as exc:  # noqa: BLE001
        err = safe_error(exc)
        logger.warning("send failed for message %s: %s", message_id, err)
        orepo.update_message(message_id, status="failed")
        repo.add_audit("send_email_failed", "outreach_message", message_id, {"error": err})
        raise ValueError(f"Sending failed: {err}") from exc

    orepo.update_message(message_id, status="sent", sent_at=utcnow(), subject=subject,
                         gmail_message_id=res.get("gmail_message_id"), rfc822_message_id=res.get("rfc822_message_id"),
                         in_reply_to=in_reply_to)
    orepo.set_thread(t["id"], status="waiting", gmail_thread_id=t.get("gmail_thread_id") or res.get("gmail_thread_id"))
    repo.add_audit("send_email", "outreach_message", message_id, {"to": to, "provider": acct["provider"]})
    if t["job"] and repo.get_job(t["job_id"])["status"] == "new":
        repo.update_job_status(t["job_id"], "applied")
    return orepo.get_thread(t["id"])


def mark_thread(thread_id: int, status: str) -> dict:
    if status not in ("sent", "replied", "waiting", "closed", "skipped"):
        raise ValueError("Invalid status")
    t = orepo.get_thread(thread_id)
    if not t:
        raise LookupError("Thread not found")
    if status == "sent" and t["channel"] == "linkedin":
        for m in t["messages"]:
            if m["direction"] == "outbound" and m["status"] in ("draft", "approved"):
                orepo.update_message(m["id"], status="sent", sent_at=utcnow())
        status = "waiting"
    orepo.set_thread(thread_id, status=status)
    repo.add_audit("mark_thread", "outreach_thread", thread_id, {"status": status})
    return orepo.get_thread(thread_id)


# ── Replies ────────────────────────────────────────────────────────────────────

class ReplyClass(BaseModel):
    category: Literal["interested", "interview_request", "needs_info", "not_a_fit", "out_of_office", "other"]
    summary: str = ""


async def _classify(text: str) -> ReplyClass:
    if not settings.bedrock_configured:
        return ReplyClass(category="other", summary="")
    try:
        return await _run_llm(ReplyClass, "Classify this reply to a job outreach email and summarise it in one line.",
                              text[:4000])
    except Exception as exc:  # noqa: BLE001
        logger.warning("reply classification failed: %s", safe_error(exc))
        return ReplyClass(category="other")


async def check_replies() -> dict:
    """Read only threads the app started. Store new inbound messages and classify them."""
    acct = orepo.get_email_account()
    if not acct:
        return {"checked": 0, "new_replies": 0, "message": "No email account connected"}
    new = 0
    checked = 0
    if acct["provider"] == "gmail_api":
        creds, acct_full = _gmail_creds()
        me = acct_full["email_address"].lower()
        for t in orepo.tracked_gmail_threads():
            checked += 1
            try:
                messages = await run_in_threadpool(gmail.get_thread, creds, t["gmail_thread_id"])
            except Exception as exc:  # noqa: BLE001
                logger.warning("gmail thread %s read failed: %s", t["id"], safe_error(exc))
                continue
            known = orepo.known_gmail_message_ids(t["id"])
            for gm in messages:
                sender = parseaddr(gm["from"])[1].lower()
                if gm["gmail_message_id"] in known or sender == me or "SENT" in gm["label_ids"]:
                    continue
                body = gmail.strip_quoted(gm["body"])
                cls = await _classify(body)
                orepo.add_message(t["id"], "inbound", body, "received", subject=gm["subject"],
                                  gmail_message_id=gm["gmail_message_id"], rfc822_message_id=gm["rfc822_message_id"],
                                  in_reply_to=gm["in_reply_to"],
                                  received_at=datetime.fromtimestamp(gm["internal_date_ms"] / 1000, tz=timezone.utc)
                                  .replace(tzinfo=None) if gm["internal_date_ms"] else utcnow(),
                                  reply_category=cls.category, drafted_by="user")
                orepo.set_thread(t["id"], status="replied")
                new += 1
    else:
        sent = orepo.outbound_sent_smtp()
        by_id = {s["rfc822_message_id"]: s["thread_id"] for s in sent}
        checked = len(by_id)
        known = orepo.known_rfc822_ids()
        try:
            replies = await run_in_threadpool(smtp_mail.find_replies, list(by_id))
        except Exception as exc:  # noqa: BLE001
            return {"checked": checked, "new_replies": 0, "message": f"IMAP failed: {safe_error(exc)}"}
        for r in replies:
            if r["rfc822_message_id"] in known:
                continue
            tid = by_id.get(r["replying_to"])
            if not tid:
                continue
            body = gmail.strip_quoted(r["body"])
            cls = await _classify(body)
            orepo.add_message(tid, "inbound", body, "received", subject=r["subject"],
                              rfc822_message_id=r["rfc822_message_id"], in_reply_to=r["in_reply_to"],
                              received_at=r["date"].replace(tzinfo=None) if r["date"] else utcnow(),
                              reply_category=cls.category, drafted_by="user")
            orepo.set_thread(tid, status="replied")
            new += 1
    return {"checked": checked, "new_replies": new, "message": ""}


def add_linkedin_reply(thread_id: int, text: str) -> dict:
    t = orepo.get_thread(thread_id)
    if not t:
        raise LookupError("Thread not found")
    orepo.add_message(thread_id, "inbound", text.strip(), "received", received_at=utcnow(), drafted_by="user")
    orepo.set_thread(thread_id, status="replied")
    return orepo.get_thread(thread_id)


class NextReply(BaseModel):
    subject: str = ""
    body: str
    notes_for_user: str = Field(default="", description="Anything the user must check or fill in before sending")


async def draft_reply(thread_id: int, guidance: str = "") -> dict:
    t = orepo.get_thread(thread_id)
    if not t:
        raise LookupError("Thread not found")
    if not any(m["direction"] == "inbound" for m in t["messages"]):
        raise ValueError("No reply in this thread yet")
    job = repo.get_job(t["job_id"])
    ctx = _context(job, t["contact"] or {})
    history = "\n\n".join(f"[{m['direction'].upper()}] {m.get('subject') or ''}\n{m['body']}" for m in t["messages"]
                          if m["status"] in ("sent", "received"))
    slots = orepo.list_slots()
    slots_text = "\n".join(f"- {s['starts_at']} to {s['ends_at']} ({s['timezone']})" for s in slots) or \
        "No availability entered. Do not propose specific times; ask them to suggest times."
    result = await _run_llm(
        NextReply, OUTREACH_SYSTEM,
        f"{ctx}\n\nConversation so far:\n{history}\n\nCandidate availability:\n{slots_text}\n\n"
        f"Extra guidance from the candidate: {guidance or 'none'}\n\nWrite the candidate's next reply "
        f"({'email' if t['channel'] == 'email' else 'LinkedIn message'}).")
    attachments = []
    if t["channel"] == "email" and t.get("cv_version_id"):
        v = crepo.get_version(t["cv_version_id"])
        attachments = [v["pdf_path"]] if v and v.get("pdf_path") else []
    m = orepo.add_message(thread_id, "outbound", result.body, "draft",
                          subject=result.subject or (t["messages"][0].get("subject") or ""), attachments=attachments)
    out = orepo.get_thread(thread_id)
    out["notes_for_user"] = result.notes_for_user
    out["draft_message_id"] = m["id"]
    return out


# ── Availability ───────────────────────────────────────────────────────────────

def add_slot(starts_at: datetime, ends_at: datetime, tz: str) -> dict:
    if ends_at <= starts_at:
        raise ValueError("End must be after start")
    return orepo.add_slot(starts_at.replace(tzinfo=None), ends_at.replace(tzinfo=None), tz)


# ── Refine drafts and delete threads ───────────────────────────────────────────

async def refine_draft(message_id: int, instruction: str) -> dict:
    """Rewrite an unsent draft (a first message or a reply draft) following the owner's instruction.
    The draft goes back to 'draft', so it must be approved again before it can be sent."""
    m = orepo.get_message(message_id)
    if not m:
        raise LookupError("Message not found")
    if m["direction"] != "outbound" or m["status"] not in ("draft", "approved", "failed"):
        raise ValueError("Only drafts that have not been sent can be refined")
    instruction = (instruction or "").strip()
    if not instruction:
        raise ValueError("Say what to change, e.g. 'shorter, mention the SOC project'")
    t = orepo.get_thread(m["thread_id"])
    if not t:
        raise LookupError("Thread not found")
    job = t.get("job") or {}
    full_job = repo.get_job(job["id"]) if job.get("id") else None
    ctx = _context(full_job or job, t.get("contact") or {})
    history = "\n".join(f"{x['direction']}: {x['body']}" for x in t["messages"] if x["id"] != m["id"])[-3000:]
    prompt = (f"{ctx}\n\nCurrent draft subject: {m.get('subject') or ''}\nCurrent draft:\n{m['body']}\n\n"
              f"Earlier messages in this thread:\n{history or '(none)'}\n\n"
              f"Rewrite the draft following this instruction: {instruction}\n"
              "Keep the same purpose and the same channel length limits. Keep only facts that are already in the "
              "draft, the job, the profile or the instruction.")
    if t["channel"] == "email":
        d = await _run_llm(EmailDraft, OUTREACH_SYSTEM, prompt)
        orepo.update_message(m["id"], subject=d.subject, body=d.body, status="draft")
    else:
        d = await _run_llm(LinkedInDraft, OUTREACH_SYSTEM, prompt)
        orepo.update_message(m["id"], subject=d.connection_note[:300], body=d.message, status="draft")
    repo.add_audit("refine_draft", "outreach_message", m["id"], {"instruction": instruction[:300]})
    return orepo.get_thread(m["thread_id"])


def delete_thread(thread_id: int) -> bool:
    """Remove a thread and its messages from this app. Emails already sent stay in the owner's Gmail."""
    t = orepo.get_thread(thread_id)
    if not t:
        raise LookupError("Thread not found")
    had_sent = any(m["status"] == "sent" for m in t["messages"])
    orepo.delete_thread(thread_id)
    repo.add_audit("delete_thread", "outreach_thread", thread_id,
                   {"channel": t["channel"], "had_sent_messages": had_sent})
    return True


# ── Attach or create the CV from a draft ───────────────────────────────────────

def attach_cv(message_id: int) -> dict:
    """Attach the generated PDF for this job (or its group) to an unsent email draft."""
    from db import cv_repository as crepo

    m = orepo.get_message(message_id)
    if not m:
        raise LookupError("Message not found")
    if m["direction"] != "outbound" or m["status"] not in ("draft", "approved", "failed"):
        raise ValueError("Only drafts that have not been sent can get a CV")
    t = orepo.get_thread(m["thread_id"])
    if not t or t["channel"] != "email":
        raise ValueError("CVs are attached to email drafts only")
    cv = crepo.version_for_job(t["job_id"])
    if not cv or not cv.get("pdf_path"):
        waiting = [v for v in crepo.list_versions() if v.get("job_id") == t["job_id"] and v["status"] != "generated"]
        if waiting:
            raise LookupError(
                f"CV version #{waiting[0]['id']} for this job is waiting for your decision. In Matches and CVs > "
                "Tailored CVs, approve or reject its suggested changes, click 'Approve and create DOCX and PDF', "
                "then click Attach CV here again.")
        raise LookupError("No generated CV for this job yet. Use 'Create CV for this job' first.")
    update_draft(message_id, m.get("subject"), m["body"], [cv["pdf_path"]])
    orepo.set_thread(m["thread_id"], cv_version_id=cv["id"])
    repo.add_audit("attach_cv", "outreach_message", message_id, {"cv_version_id": cv["id"]})
    return {"status": "attached", "cv_version_id": cv["id"]}


async def make_cv(message_id: int) -> dict:
    """Run the same CV process as the Tailored CVs tab. Reuses an unfinished version for this job.
    If no changes need a decision, the files are generated and attached right away. Otherwise the
    owner reviews the changes first (approval stays a button click, never done by the agent)."""
    from db import cv_repository as crepo
    from services import cv_service

    m = orepo.get_message(message_id)
    if not m:
        raise LookupError("Message not found")
    if m["direction"] != "outbound" or m["status"] not in ("draft", "approved", "failed"):
        raise ValueError("Only drafts that have not been sent can get a CV")
    t = orepo.get_thread(m["thread_id"])
    if not t or t["channel"] != "email":
        raise ValueError("CVs are attached to email drafts only")
    job_id = t["job_id"]
    if crepo.version_for_job(job_id):
        return {**attach_cv(message_id), "status": "attached"}
    unfinished = [v for v in crepo.list_versions() if v.get("job_id") == job_id and v["status"] != "generated"]
    version = unfinished[0] if unfinished else await cv_service.propose_changes(job_id=job_id)
    pending = sum(1 for p in version["proposals"] if p["status"] == "proposed")
    if pending:
        return {"status": "needs_review", "cv_version_id": version["id"], "pending": pending}
    await cv_service.generate(version["id"])
    return {**attach_cv(message_id), "status": "attached"}
