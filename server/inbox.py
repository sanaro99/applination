"""Inbox sync — read recruiter replies and advance application status.

Scans the configured Gmail/IMAP inbox, matches messages to in-flight
applications by company, classifies each with the LLM, and applies conservative
forward-only status transitions (generated → applied → interviewing →
rejected/offer). Idempotent: every classified (message, application) pair is
recorded so re-syncing never double-counts.

Configuration lives under ``inbox:`` in config.yaml. Disabled by default.
"""
from __future__ import annotations
import json
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from .db import Application, ApplicationStatus, Setting, session
from .deps import load_config

router = APIRouter(prefix="/api/inbox", tags=["inbox"])
log = logging.getLogger("server.inbox")

_PROCESSED_KEY = "inbox_processed_ids"
_LAST_SYNC_KEY = "inbox_last_sync"
_PROCESSED_CAP = 2000

# Forward-progress ordering. A transition is applied only when it moves an
# application to a strictly higher rank (so a stray rejection never downgrades
# an offer, and an auto-ack never un-does an interview). `archived` is opt-out.
_RANK = {
    ApplicationStatus.generated: 0,
    ApplicationStatus.applied: 1,
    ApplicationStatus.interviewing: 2,
    ApplicationStatus.rejected: 3,
    ApplicationStatus.offer: 4,
}
_CATEGORY_TARGET = {
    "auto_ack": ApplicationStatus.applied,
    "interview": ApplicationStatus.interviewing,
    "rejection": ApplicationStatus.rejected,
    "offer": ApplicationStatus.offer,
}
# Applications we bother scanning for (terminal/archived ones are left alone).
_ACTIVE_STATES = (
    ApplicationStatus.generated,
    ApplicationStatus.applied,
    ApplicationStatus.interviewing,
)

_COMPANY_STOPWORDS = {
    "inc", "llc", "ltd", "corp", "corporation", "co", "company", "the",
    "group", "labs", "technologies", "technology", "tech", "systems",
    "solutions", "global", "international", "holdings", "ai",
}


# --------------------------------------------------------------------------
# config + small helpers
# --------------------------------------------------------------------------
def _inbox_cfg() -> dict:
    return (load_config().get("inbox") or {})


def _to_naive_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _company_tokens(company: str) -> list[str]:
    toks = re.split(r"[^a-z0-9]+", (company or "").lower())
    return [t for t in toks if len(t) >= 3 and t not in _COMPANY_STOPWORDS]


def _email_matches_app(msg, tokens: list[str], company_norm: str) -> bool:
    if not tokens and not company_norm:
        return False
    hay_strong = f"{msg.from_name} {msg.domain} {msg.subject}".lower()
    if any(t in hay_strong for t in tokens):
        return True
    # Full company name appearing in the body is a weaker but still useful signal.
    return bool(company_norm) and company_norm in (msg.body or "").lower()


def _load_processed() -> set[str]:
    with session() as s:
        row = s.get(Setting, _PROCESSED_KEY)
    if not row or not row.value:
        return set()
    try:
        return set(json.loads(row.value))
    except Exception:
        return set()


def _save_processed(ids: set[str]) -> None:
    capped = list(ids)[-_PROCESSED_CAP:]
    with session() as s:
        row = s.get(Setting, _PROCESSED_KEY)
        if row is None:
            row = Setting(key=_PROCESSED_KEY, value="")
        row.value = json.dumps(capped)
        s.add(row)
        s.commit()


def _set_setting(key: str, value: str) -> None:
    with session() as s:
        row = s.get(Setting, key)
        if row is None:
            row = Setting(key=key, value="")
        row.value = value
        s.add(row)
        s.commit()


def _get_setting(key: str) -> str:
    with session() as s:
        row = s.get(Setting, key)
        return row.value if row else ""


# --------------------------------------------------------------------------
# endpoints
# --------------------------------------------------------------------------
class InboxStatus(BaseModel):
    configured: bool
    enabled: bool
    email_masked: str
    scan_days: int
    last_sync: str | None
    auto_update_status: bool


def _mask(addr: str) -> str:
    if "@" not in addr:
        return addr
    local, dom = addr.split("@", 1)
    shown = local[:2] + "***" if len(local) > 2 else "***"
    return f"{shown}@{dom}"


@router.get("/status", response_model=InboxStatus)
def inbox_status() -> InboxStatus:
    cfg = _inbox_cfg()
    addr = str(cfg.get("email") or "")
    has_creds = bool(addr) and bool(cfg.get("app_password"))
    last = _get_setting(_LAST_SYNC_KEY)
    return InboxStatus(
        configured=has_creds,
        enabled=bool(cfg.get("enabled", False)) and has_creds,
        email_masked=_mask(addr) if addr else "",
        scan_days=int(cfg.get("scan_days", 30) or 30),
        last_sync=last or None,
        auto_update_status=bool(cfg.get("auto_update_status", True)),
    )


@router.post("/test")
def inbox_test() -> dict:
    from src.inbox import verify_connection, InboxError
    cfg = _inbox_cfg()
    try:
        verify_connection(
            str(cfg.get("email") or ""),
            str(cfg.get("app_password") or ""),
            host=str(cfg.get("imap_host") or "imap.gmail.com"),
            port=int(cfg.get("imap_port", 993) or 993),
        )
    except InboxError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


class SyncBody(BaseModel):
    days: int | None = None


class SyncUpdate(BaseModel):
    application_id: int
    company: str
    title: str
    from_email: str
    category: str
    confidence: float
    old_status: str
    new_status: str
    summary: str


class SyncResult(BaseModel):
    scanned: int
    matched: int
    classified: int
    updates: list[SyncUpdate]
    skipped_low_confidence: int
    error: str | None = None


@router.post("/sync", response_model=SyncResult)
def inbox_sync(body: SyncBody | None = None) -> SyncResult:
    from src.inbox import InboxScanner, InboxError, classify_email
    from src.providers import get_provider_chain

    cfg = _inbox_cfg()
    address = str(cfg.get("email") or "")
    password = str(cfg.get("app_password") or "")
    if not address or not password:
        raise HTTPException(
            400, "Inbox not configured. Set inbox.email and inbox.app_password."
        )
    days = (body.days if body and body.days else int(cfg.get("scan_days", 30) or 30))
    min_conf = float(cfg.get("min_confidence", 0.6) or 0.6)
    auto_update = bool(cfg.get("auto_update_status", True))
    max_classifications = int(cfg.get("max_classifications", 80) or 80)

    # 1. fetch
    try:
        scanner = InboxScanner(
            address, password,
            host=str(cfg.get("imap_host") or "imap.gmail.com"),
            port=int(cfg.get("imap_port", 993) or 993),
        )
        emails = scanner.fetch_since(days=days)
    except InboxError as e:
        raise HTTPException(400, str(e))

    # 2. active applications
    full_cfg = load_config()
    with session() as s:
        apps = s.exec(
            select(Application).where(Application.status.in_(_ACTIVE_STATES))  # type: ignore[attr-defined]
        ).all()

    processed = _load_processed()
    chain = get_provider_chain(full_cfg["llm"])

    matched = 0
    classified = 0
    skipped = 0
    updates: list[SyncUpdate] = []

    for app in apps:
        tokens = _company_tokens(app.company)
        company_norm = (app.company or "").strip().lower()
        candidates = [
            m for m in emails if _email_matches_app(m, tokens, company_norm)
        ][:5]  # most-recent few per app
        for msg in candidates:
            mid = f"{msg.message_id or msg.uid}|{app.id}"
            if mid in processed:
                continue
            matched += 1
            if classified >= max_classifications:
                continue
            processed.add(mid)
            result = classify_email(chain, msg, company=app.company, title=app.title)
            classified += 1
            upd = _apply_result(app.id, msg, result, min_conf, auto_update)
            if upd is None:
                if result["category"] in _CATEGORY_TARGET and result["confidence"] < min_conf:
                    skipped += 1
                continue
            updates.append(upd)

    _save_processed(processed)
    _set_setting(_LAST_SYNC_KEY, datetime.utcnow().isoformat())

    return SyncResult(
        scanned=len(emails),
        matched=matched,
        classified=classified,
        updates=updates,
        skipped_low_confidence=skipped,
    )


def _apply_result(
    app_id: int | None, msg, result: dict, min_conf: float, auto_update: bool
) -> SyncUpdate | None:
    """Apply a classification to one application; returns the update or None."""
    category = result["category"]
    confidence = result["confidence"]
    if app_id is None or category == "other":
        return None
    target = _CATEGORY_TARGET.get(category)
    if target is None or confidence < min_conf:
        return None

    with session() as s:
        app = s.get(Application, app_id)
        if app is None or app.status == ApplicationStatus.archived:
            return None
        old = app.status
        # last_email_at is informational; always record the freshest email.
        email_dt = _to_naive_utc(msg.date) or datetime.utcnow()
        if app.last_email_at is None or email_dt > app.last_email_at:
            app.last_email_at = email_dt

        advanced = False
        if auto_update and _RANK.get(target, 0) > _RANK.get(old, 0):
            app.status = target
            advanced = True
            if target in (ApplicationStatus.applied, ApplicationStatus.interviewing,
                          ApplicationStatus.offer) and app.applied_at is None:
                app.applied_at = email_dt
        if category == "interview" and result.get("interview_date"):
            app.interview_at = _to_naive_utc(result["interview_date"])

        # Always leave a breadcrumb in notes, even if status didn't advance.
        stamp = (msg.date or datetime.utcnow()).strftime("%Y-%m-%d")
        note = (
            f"[inbox {stamp}] {category} "
            f"({int(confidence * 100)}%) — {result.get('summary', '')} "
            f"· from {msg.from_email}"
        ).strip()
        app.notes = (app.notes + "\n" + note).strip() if app.notes else note
        s.add(app)
        s.commit()

        if not advanced:
            return None
        return SyncUpdate(
            application_id=app_id,
            company=app.company,
            title=app.title,
            from_email=msg.from_email,
            category=category,
            confidence=confidence,
            old_status=old.value,
            new_status=app.status.value,
            summary=result.get("summary", ""),
        )
