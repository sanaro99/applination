"""Inbox sync — read recruiter replies and advance application status.

Scans the Gmail inbox (via OAuth + the Gmail API), matches messages to
in-flight applications by company, classifies each with the LLM, and applies
conservative forward-only status transitions (generated → applied →
interviewing → rejected/offer). Idempotent: every classified (message,
application) pair is recorded so re-syncing never double-counts.

OAuth client id/secret live under ``inbox:`` in config.yaml; the access/refresh
token lives in the ``Setting`` table (see ``server/gmail_auth.py``). Disabled
until both are present.
"""
from __future__ import annotations
import json
import logging
import re
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlmodel import select

from . import gmail_auth
from .db import Application, ApplicationStatus, Setting, session
from .deps import load_config, update_config

router = APIRouter(prefix="/api/inbox", tags=["inbox"])
log = logging.getLogger("server.inbox")

_PROCESSED_KEY = "inbox_processed_ids"
_LAST_SYNC_KEY = "inbox_last_sync"
_OAUTH_STATE_KEY = "inbox_oauth_state"
_PROCESSED_CAP = 2000
_DEFAULT_REDIRECT_URI = "http://127.0.0.1:8000/api/inbox/oauth/callback"

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
    account_email: str
    has_client_credentials: bool
    redirect_uri: str
    scan_days: int
    last_sync: str | None
    auto_update_status: bool


@router.get("/status", response_model=InboxStatus)
def inbox_status() -> InboxStatus:
    cfg = _inbox_cfg()
    has_client = bool(cfg.get("client_id")) and bool(cfg.get("client_secret"))
    connected = gmail_auth.is_connected()
    last = _get_setting(_LAST_SYNC_KEY)
    return InboxStatus(
        configured=connected,
        enabled=bool(cfg.get("enabled", False)) and connected,
        account_email=gmail_auth.account_email() or "",
        has_client_credentials=has_client,
        redirect_uri=str(cfg.get("redirect_uri") or _DEFAULT_REDIRECT_URI),
        scan_days=int(cfg.get("scan_days", 30) or 30),
        last_sync=last or None,
        auto_update_status=bool(cfg.get("auto_update_status", True)),
    )


class OAuthCredentials(BaseModel):
    client_id: str
    client_secret: str


@router.put("/oauth/credentials")
def set_oauth_credentials(body: OAuthCredentials) -> dict:
    def mut(data: dict) -> None:
        inbox = data.get("inbox")
        if inbox is None:
            inbox = {}
            data["inbox"] = inbox
        inbox["client_id"] = body.client_id
        inbox["client_secret"] = body.client_secret
        inbox.setdefault("redirect_uri", _DEFAULT_REDIRECT_URI)

    update_config(mut)
    return {"ok": True}


@router.get("/oauth/authorize")
def oauth_authorize() -> RedirectResponse:
    from src.gmail_oauth import build_auth_url

    cfg = _inbox_cfg()
    client_id = str(cfg.get("client_id") or "")
    client_secret = str(cfg.get("client_secret") or "")
    redirect_uri = str(cfg.get("redirect_uri") or _DEFAULT_REDIRECT_URI)
    if not client_id or not client_secret:
        raise HTTPException(400, "Set inbox.client_id and inbox.client_secret first.")

    state = secrets.token_urlsafe(24)
    _set_setting(_OAUTH_STATE_KEY, state)
    url = build_auth_url(client_id, client_secret, redirect_uri, state)
    return RedirectResponse(url)


@router.get("/oauth/callback")
def oauth_callback(code: str | None = None, state: str | None = None, error: str | None = None) -> HTMLResponse:
    from src.gmail_oauth import exchange_code, credentials_to_token_json, get_account_email

    import html as _html

    def _page(message: str, ok: bool) -> HTMLResponse:
        return HTMLResponse(
            "<html><body style=\"font-family:sans-serif;padding:2rem\">"
            f"<p>{_html.escape(message)}</p>"
            "<script>"
            f"window.opener && window.opener.postMessage('gmail-{'connected' if ok else 'error'}', '*');"
            "window.close();"
            "</script>"
            "</body></html>"
        )

    if error:
        return _page(f"Google sign-in failed: {error}. You can close this window.", False)

    expected_state = _get_setting(_OAUTH_STATE_KEY)
    if not code or not state or state != expected_state:
        return _page("Invalid or expired sign-in attempt. You can close this window and try again.", False)
    _set_setting(_OAUTH_STATE_KEY, "")

    cfg = _inbox_cfg()
    client_id = str(cfg.get("client_id") or "")
    client_secret = str(cfg.get("client_secret") or "")
    redirect_uri = str(cfg.get("redirect_uri") or _DEFAULT_REDIRECT_URI)
    try:
        creds = exchange_code(client_id, client_secret, redirect_uri, code)
        email = get_account_email(creds)
        gmail_auth.save_token(credentials_to_token_json(creds), email)
    except Exception as e:
        log.warning("inbox: oauth exchange failed: %s", e)
        return _page(f"Could not complete Google sign-in: {e}", False)

    return _page(f"Connected as {email}. You can close this window.", True)


@router.post("/oauth/disconnect")
def oauth_disconnect() -> dict:
    gmail_auth.clear_token()
    return {"ok": True}


@router.post("/test")
def inbox_test() -> dict:
    from src.gmail_oauth import get_account_email

    creds = gmail_auth.get_credentials()
    if creds is None:
        raise HTTPException(400, "Gmail is not connected yet.")
    try:
        get_account_email(creds)
    except Exception as e:
        raise HTTPException(400, f"Gmail API call failed: {e}")
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
    from src.gmail_api import GmailApiScanner
    from src.inbox import classify_email
    from src.providers import get_provider_chain

    cfg = _inbox_cfg()
    creds = gmail_auth.get_credentials()
    if creds is None:
        raise HTTPException(400, "Gmail is not connected. Connect it from the Config page.")
    days = (body.days if body and body.days else int(cfg.get("scan_days", 30) or 30))
    min_conf = float(cfg.get("min_confidence", 0.6) or 0.6)
    auto_update = bool(cfg.get("auto_update_status", True))
    max_classifications = int(cfg.get("max_classifications", 80) or 80)

    # 1. fetch
    try:
        scanner = GmailApiScanner(creds)
        emails = scanner.fetch_since(days=days)
    except Exception as e:
        raise HTTPException(400, f"Gmail fetch failed: {e}")

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
