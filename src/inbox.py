"""Read a Gmail (or any IMAP) inbox and classify recruiter replies.

Stdlib-only (``imaplib`` + ``email``) so the standalone app needs no Google
OAuth — just a Gmail address and an app password. This module is engine-side:
it knows nothing about the DB. The server (``server/inbox.py``) owns matching
emails to applications and applying status changes.

Classification reuses the provider abstraction so it honors the user's
configured LLM chain and anti-fabrication conventions.
"""
from __future__ import annotations
import email as _email
import imaplib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime
from typing import Iterable

from .providers import LLMProvider, try_chain
from .scrapers.schema import strip_html

LOG = logging.getLogger(__name__)

# Outcome categories the classifier may assign to a recruiter email.
CATEGORIES = ("auto_ack", "interview", "rejection", "offer", "other")

_CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": list(CATEGORIES)},
        "confidence": {"type": "number"},
        "summary": {"type": "string"},
        "interview_date": {"type": ["string", "null"]},
    },
    "required": ["category", "confidence"],
}


class InboxError(RuntimeError):
    """IMAP connectivity / auth failure."""


@dataclass
class InboxEmail:
    uid: str
    message_id: str
    from_name: str
    from_email: str
    subject: str
    date: datetime | None
    body: str  # plain text, truncated

    @property
    def domain(self) -> str:
        return self.from_email.rsplit("@", 1)[-1].lower() if "@" in self.from_email else ""


def _decode(raw: str | None) -> str:
    """Decode an RFC 2047 encoded header to a plain string."""
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw))).strip()
    except Exception:
        return raw.strip()


def _extract_body(msg: _email.message.Message) -> str:
    """Best-effort plain-text body: prefer text/plain, fall back to stripped HTML."""
    plain, html = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp.lower():
                continue
            if ctype not in ("text/plain", "text/html"):
                continue
            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                charset = part.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="replace")
            except Exception:
                continue
            if ctype == "text/plain" and not plain:
                plain = text
            elif ctype == "text/html" and not html:
                html = text
    else:
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace") if payload else ""
        except Exception:
            text = ""
        if msg.get_content_type() == "text/html":
            html = text
        else:
            plain = text
    body = plain or (strip_html(html) if html else "")
    return body.strip()


def _parse_message(uid: str, raw: bytes) -> InboxEmail:
    msg = _email.message_from_bytes(raw)
    name, addr = parseaddr(_decode(msg.get("From")))
    try:
        dt = parsedate_to_datetime(msg.get("Date")) if msg.get("Date") else None
    except (TypeError, ValueError):
        dt = None
    return InboxEmail(
        uid=uid,
        message_id=(msg.get("Message-ID") or "").strip(),
        from_name=name or "",
        from_email=(addr or "").lower(),
        subject=_decode(msg.get("Subject")),
        date=dt,
        body=_extract_body(msg)[:4000],
    )


class InboxScanner:
    """Thin IMAP reader. Use as a context manager or call ``fetch_since``."""

    def __init__(
        self,
        address: str,
        app_password: str,
        host: str = "imap.gmail.com",
        port: int = 993,
        mailbox: str = "INBOX",
    ):
        if not address or not app_password:
            raise InboxError("inbox email and app password are required")
        self.address = address
        self.app_password = app_password
        self.host = host
        self.port = port
        self.mailbox = mailbox

    def fetch_since(self, days: int = 30, limit: int = 400) -> list[InboxEmail]:
        """Return parsed emails received in the last ``days`` (most recent first)."""
        since = (datetime.now(timezone.utc) - timedelta(days=max(1, days)))
        since_str = since.strftime("%d-%b-%Y")
        out: list[InboxEmail] = []
        try:
            M = imaplib.IMAP4_SSL(self.host, self.port)
        except Exception as e:
            raise InboxError(f"could not connect to {self.host}:{self.port} — {e}") from e
        try:
            try:
                M.login(self.address, self.app_password)
            except imaplib.IMAP4.error as e:
                raise InboxError(
                    "IMAP login failed. For Gmail use an App Password "
                    "(not your account password) and enable IMAP. "
                    f"Server said: {e}"
                ) from e
            M.select(self.mailbox, readonly=True)
            typ, data = M.search(None, "SINCE", since_str)
            if typ != "OK" or not data or not data[0]:
                return []
            ids = data[0].split()
            for num in reversed(ids[-limit:]):
                try:
                    typ, msg_data = M.fetch(num, "(RFC822)")
                    if typ != "OK" or not msg_data:
                        continue
                    raw = next(
                        (p[1] for p in msg_data if isinstance(p, tuple) and p[1]),
                        None,
                    )
                    if raw:
                        out.append(_parse_message(num.decode(errors="replace"), raw))
                except Exception as e:  # one bad message shouldn't sink the scan
                    LOG.warning("inbox: failed to fetch/parse a message: %s", e)
        finally:
            try:
                M.logout()
            except Exception:
                pass
        return out


def verify_connection(
    address: str, app_password: str, host: str = "imap.gmail.com", port: int = 993
) -> None:
    """Raise InboxError if we can't log in; return None on success."""
    try:
        M = imaplib.IMAP4_SSL(host, port)
    except Exception as e:
        raise InboxError(f"could not connect to {host}:{port} — {e}") from e
    try:
        M.login(address, app_password)
    except imaplib.IMAP4.error as e:
        raise InboxError(f"login failed — {e}") from e
    finally:
        try:
            M.logout()
        except Exception:
            pass


def classify_email(
    chain: list[LLMProvider],
    msg: InboxEmail,
    *,
    company: str,
    title: str,
) -> dict:
    """Classify one recruiter email against the application it likely concerns.

    Returns ``{category, confidence, summary, interview_date}`` where category
    is one of CATEGORIES and confidence is 0..1. Never fabricates outcomes:
    when unsure the model is instructed to return ``other`` with low confidence.
    """
    system = (
        "You triage emails a job applicant receives after applying. Decide what "
        "an email means for ONE specific application. Categories:\n"
        "- auto_ack: automated 'we received your application' acknowledgement.\n"
        "- interview: invitation to interview, schedule a call, or take an "
        "assessment/OA.\n"
        "- rejection: the application was declined / position filled / not moving "
        "forward.\n"
        "- offer: a job/internship offer is extended.\n"
        "- other: newsletters, unrelated mail, or anything that does not clearly "
        "fit the above.\n\n"
        "BINDING RULES: Judge ONLY from the email text. If the email is not "
        "clearly about THIS company/role, or is ambiguous, return category "
        "'other' with low confidence. Do not infer an outcome that the text does "
        "not state. confidence is your certainty from 0.0 to 1.0. If the email "
        "proposes a specific interview date/time, put it in interview_date as an "
        "ISO 8601 string (YYYY-MM-DD or YYYY-MM-DDTHH:MM); otherwise null."
    )
    user = (
        f"APPLICATION: {title} at {company}\n\n"
        f"EMAIL FROM: {msg.from_name} <{msg.from_email}>\n"
        f"SUBJECT: {msg.subject}\n"
        f"DATE: {msg.date.isoformat() if msg.date else 'unknown'}\n\n"
        f"BODY:\n{msg.body[:2500]}"
    )
    try:
        out = try_chain(
            chain,
            lambda p: p.json_call(system, user, max_tokens=300, schema=_CLASSIFY_SCHEMA),
            any_error=True,
            task_name="inbox_classify",
        )
    except Exception as e:
        LOG.warning("inbox: classify failed: %s", e)
        return {"category": "other", "confidence": 0.0, "summary": "", "interview_date": None}

    category = str(out.get("category", "other")).strip().lower()
    if category not in CATEGORIES:
        category = "other"
    try:
        confidence = max(0.0, min(1.0, float(out.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "category": category,
        "confidence": confidence,
        "summary": str(out.get("summary", "") or "")[:500],
        "interview_date": _coerce_dt(out.get("interview_date")),
    }


def _coerce_dt(val) -> datetime | None:
    if not val or not isinstance(val, str):
        return None
    raw = val.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None
