"""Gmail API for your personal Gmail: OAuth connect, send one message, read threads the app started.

Scopes are gmail.send and gmail.readonly only. The Google client library is synchronous;
callers run these functions in a worker thread.
"""

from __future__ import annotations

import base64
import mimetypes
import re
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

from config import settings

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def client_file_ready() -> bool:
    return bool(settings.GMAIL_OAUTH_CLIENT_FILE) and Path(settings.GMAIL_OAUTH_CLIENT_FILE).is_file()


def run_oauth_flow() -> str:
    """Open the Google consent screen in your browser and return the credentials as JSON.

    Runs a short-lived local server on a random localhost port to receive the redirect.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not client_file_ready():
        raise RuntimeError("GMAIL_OAUTH_CLIENT_FILE is not set or the file does not exist")
    flow = InstalledAppFlow.from_client_secrets_file(settings.GMAIL_OAUTH_CLIENT_FILE, SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True, access_type="offline", prompt="consent")
    return creds.to_json()


def load_credentials(token_json: str):
    """Return (credentials, refreshed_token_json_or_None)."""
    import json

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
    refreshed = None
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        refreshed = creds.to_json()
    return creds, refreshed


def _service(creds):
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def account_email(creds) -> str:
    return _service(creds).users().getProfile(userId="me").execute().get("emailAddress", "")


def build_message(sender: str, to: str, subject: str, body: str, attachments: list[str],
                  in_reply_to: str | None = None, references: str | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=(sender.split("@")[-1] if "@" in sender else None))
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = references or in_reply_to
    msg.set_content(body)
    for path in attachments:
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"Attachment missing: {p.name}")
        ctype, _ = mimetypes.guess_type(p.name)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(p.read_bytes(), maintype=maintype, subtype=subtype, filename=p.name)
    return msg


def send(creds, msg: EmailMessage, thread_id: str | None = None) -> dict:
    """Send one message. Returns {gmail_message_id, gmail_thread_id, rfc822_message_id}."""
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    body: dict = {"raw": raw}
    if thread_id:
        body["threadId"] = thread_id
    svc = _service(creds)
    sent = svc.users().messages().send(userId="me", body=body).execute()
    meta = svc.users().messages().get(userId="me", id=sent["id"], format="metadata",
                                      metadataHeaders=["Message-ID"]).execute()
    headers = {h["name"].lower(): h["value"] for h in (meta.get("payload") or {}).get("headers") or []}
    return {"gmail_message_id": sent["id"], "gmail_thread_id": sent.get("threadId"),
            "rfc822_message_id": headers.get("message-id") or msg["Message-ID"]}


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _body_text(payload: dict) -> str:
    def walk(part: dict, mime: str) -> str:
        if part.get("mimeType") == mime and (part.get("body") or {}).get("data"):
            return _decode(part["body"]["data"])
        for sub in part.get("parts") or []:
            found = walk(sub, mime)
            if found:
                return found
        return ""

    text = walk(payload, "text/plain")
    if not text:
        html = walk(payload, "text/html")
        text = re.sub(r"<[^>]+>", " ", html)
    return text.strip()


def strip_quoted(text: str) -> str:
    """Drop the quoted history below 'On <date> ... wrote:' so only the new reply remains."""
    m = re.search(r"\n\s*On .{5,200}wrote:\s*\n", text)
    return (text[:m.start()] if m else text).strip()


def get_thread(creds, thread_id: str) -> list[dict]:
    data = _service(creds).users().threads().get(userId="me", id=thread_id, format="full").execute()
    out = []
    for m in data.get("messages") or []:
        payload = m.get("payload") or {}
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers") or []}
        out.append({
            "gmail_message_id": m.get("id"),
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "subject": headers.get("subject", ""),
            "rfc822_message_id": headers.get("message-id", ""),
            "in_reply_to": headers.get("in-reply-to", ""),
            "internal_date_ms": int(m.get("internalDate") or 0),
            "label_ids": m.get("labelIds") or [],
            "body": _body_text(payload),
        })
    return out
