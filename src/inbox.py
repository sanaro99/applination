"""Parse Gmail messages and normalize recruiter-reply classifications.

Email parsing (``_parse_message``) is transport-agnostic: it takes raw RFC822
bytes, which ``src/gmail_api.GmailApiScanner`` fetches via the Gmail API
(OAuth — see ``src/gmail_oauth.py``). This module is engine-side: it knows
nothing about the DB. The server (``server/inbox.py``) owns matching emails to
applications and applying status changes.

Classification itself runs client-side (in-browser WebLLM — see
``web/lib/webllm-classify.ts``, which ports the same prompt/schema this module
used to send to the Python provider chain) rather than through
``src/providers/``. ``normalize_classification`` validates/clamps whatever the
browser submits before it's trusted server-side.
"""
from __future__ import annotations
import email as _email
from dataclasses import dataclass
from datetime import datetime
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime

from .scrapers.schema import strip_html

# Outcome categories the classifier may assign to a recruiter email. Kept here
# as the shared contract between the (TypeScript) prompt and this module's
# validation.
CATEGORIES = ("auto_ack", "interview", "rejection", "offer", "other")


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


def normalize_classification(raw: dict) -> dict:
    """Validate/clamp a classification submitted by the browser's WebLLM call.

    Returns ``{category, confidence, summary, interview_date}`` where category
    is one of CATEGORIES and confidence is 0..1 — never trusts the client's
    values directly.
    """
    category = str((raw or {}).get("category", "other")).strip().lower()
    if category not in CATEGORIES:
        category = "other"
    try:
        confidence = max(0.0, min(1.0, float((raw or {}).get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "category": category,
        "confidence": confidence,
        "summary": str((raw or {}).get("summary", "") or "")[:500],
        "interview_date": _coerce_dt((raw or {}).get("interview_date")),
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
