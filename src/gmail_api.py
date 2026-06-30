"""Gmail API transport for inbox scanning + digest sending.

Replaces IMAP (``src/inbox.py``'s ``InboxScanner``) and SMTP
(``src/digest.py``'s ``send_email``) with calls authenticated via OAuth
credentials (see ``src/gmail_oauth.py``). ``GmailApiScanner`` returns the same
``InboxEmail`` objects IMAP did — ``messages.get(format="raw")`` hands back the
same RFC822 bytes IMAP's ``FETCH (RFC822)`` does, so the existing parser is
reused unchanged.
"""
from __future__ import annotations

import base64
import logging
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .inbox import InboxEmail, _parse_message

LOG = logging.getLogger(__name__)


class GmailApiScanner:
    """Thin Gmail API reader with the same shape as ``InboxScanner``."""

    def __init__(self, creds: Credentials):
        self.service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    def fetch_since(self, days: int = 30, limit: int = 400) -> list[InboxEmail]:
        """Return parsed emails received in the last ``days`` (most recent first)."""
        since = datetime.now(timezone.utc) - timedelta(days=max(1, days))
        query = f"after:{int(time.mktime(since.timetuple()))} in:inbox"

        ids: list[str] = []
        page_token = None
        while len(ids) < limit:
            resp = (
                self.service.users()
                .messages()
                .list(userId="me", q=query, pageToken=page_token, maxResults=min(100, limit - len(ids)))
                .execute()
            )
            ids.extend(m["id"] for m in resp.get("messages", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        out: list[InboxEmail] = []
        for msg_id in ids:
            try:
                raw_resp = (
                    self.service.users()
                    .messages()
                    .get(userId="me", id=msg_id, format="raw")
                    .execute()
                )
                raw = base64.urlsafe_b64decode(raw_resp["raw"])
                out.append(_parse_message(msg_id, raw))
            except Exception as e:  # one bad message shouldn't sink the scan
                LOG.warning("gmail: failed to fetch/parse message %s: %s", msg_id, e)
        return out


def send_via_gmail_api(
    creds: Credentials,
    *,
    sender: str,
    to: str,
    subject: str,
    html: str,
    text: str,
) -> None:
    """Send a multipart email through the Gmail API (no SMTP/app password)."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(text or "")
    msg.add_alternative(html or f"<pre>{text}</pre>", subtype="html")

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
