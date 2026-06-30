"""Parse Gmail messages and classify recruiter replies.

Email parsing (``_parse_message``) is transport-agnostic: it takes raw RFC822
bytes, which ``src/gmail_api.GmailApiScanner`` fetches via the Gmail API
(OAuth — see ``src/gmail_oauth.py``). This module is engine-side: it knows
nothing about the DB. The server (``server/inbox.py``) owns matching emails to
applications and applying status changes.

Classification reuses the provider abstraction so it honors the user's
configured LLM chain and anti-fabrication conventions.
"""
from __future__ import annotations
import email as _email
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime

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
