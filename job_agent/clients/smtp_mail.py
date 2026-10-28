"""SMTP send and IMAP reply lookup with a Gmail app password. Fallback when Gmail OAuth is not used."""

from __future__ import annotations

import email
import imaplib
import smtplib
from email.message import EmailMessage
from email.utils import parsedate_to_datetime

from config import settings


def configured() -> bool:
    return bool(settings.SMTP_USERNAME and settings.SMTP_APP_PASSWORD)


def send(msg: EmailMessage) -> dict:
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=60) as smtp:
        smtp.starttls()
        smtp.login(settings.SMTP_USERNAME, settings.SMTP_APP_PASSWORD)
        smtp.send_message(msg)
    return {"gmail_message_id": None, "gmail_thread_id": None, "rfc822_message_id": msg["Message-ID"]}


def _text(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                return (part.get_payload(decode=True) or b"").decode(part.get_content_charset() or "utf-8", "replace")
        return ""
    return (msg.get_payload(decode=True) or b"").decode(msg.get_content_charset() or "utf-8", "replace")


def find_replies(message_ids: list[str]) -> list[dict]:
    """Search INBOX for messages whose In-Reply-To or References name one of our Message-IDs."""
    found: list[dict] = []
    if not message_ids:
        return found
    with imaplib.IMAP4_SSL(settings.IMAP_HOST) as imap:
        imap.login(settings.SMTP_USERNAME, settings.SMTP_APP_PASSWORD)
        imap.select("INBOX", readonly=True)
        seen: set[bytes] = set()
        for mid in message_ids:
            for header in ("In-Reply-To", "References"):
                status, data = imap.search(None, "HEADER", header, mid)
                if status != "OK":
                    continue
                for num in (data[0] or b"").split():
                    if num in seen:
                        continue
                    seen.add(num)
                    status, msg_data = imap.fetch(num, "(RFC822)")
                    if status != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                        continue
                    msg = email.message_from_bytes(msg_data[0][1])
                    date = None
                    try:
                        date = parsedate_to_datetime(msg.get("Date"))
                    except (TypeError, ValueError):
                        pass
                    found.append({
                        "replying_to": mid,
                        "from": msg.get("From", ""),
                        "subject": msg.get("Subject", ""),
                        "rfc822_message_id": msg.get("Message-ID", ""),
                        "in_reply_to": msg.get("In-Reply-To", ""),
                        "date": date,
                        "body": _text(msg),
                    })
    return found
