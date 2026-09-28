"""Authenticated outbound bridge from hosted runs to a user's local Ollama.

Only the user's worker contacts localhost. Pending prompts live briefly in the
database so a server restart or another API process does not change ownership.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, or_, update
from sqlmodel import select
from slowapi.util import get_remote_address

from .auth import require_user
from .db import LocalOllamaGrant, LocalOllamaTask, User, session
from .scoping import find_owned, get_owned, owned
from .limits import limiter
from .time_utils import as_utc, utc_now

site_router = APIRouter(prefix="/api/local-ollama", tags=["local-ollama"])
worker_router = APIRouter(prefix="/api/local-ollama/worker", tags=["local-ollama-worker"])
pair_router = APIRouter(prefix="/api/local-ollama/worker", tags=["local-ollama-pairing"])

ONLINE_FOR = timedelta(seconds=35)
LEASE_FOR = timedelta(minutes=2)
CALL_TIMEOUT = 660
WORKER_SCRIPT = Path(__file__).resolve().parent.parent / "local_ollama_worker.py"
PAIRING_TTL = timedelta(minutes=5)
SESSION_TTL = timedelta(hours=12)
IDLE_TTL = timedelta(hours=1)
MAX_WORKER_BODY = 1024 * 1024
WORKER_LIMIT = "120/minute"


class EmptyBody(BaseModel):
    model_config = {"extra": "forbid"}


class WorkerRequestGuard:
    """Bound untrusted worker bodies before FastAPI's JSON parser allocates them."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/local-ollama/worker/"):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        # The worker is an HTTP client, not a browser integration.
        if b"origin" in headers or scope.get("query_string"):
            return await JSONResponse({"detail": "invalid worker request"}, status_code=403)(scope, receive, send)
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = -1
        if declared < 0 or declared > MAX_WORKER_BODY:
            return await JSONResponse({"detail": "worker request too large"}, status_code=413)(scope, receive, send)
        size = 0

        async def bounded_receive():
            nonlocal size
            message = await receive()
            size += len(message.get("body", b""))
            if size > MAX_WORKER_BODY:
                raise HTTPException(413, "worker request too large")
            return message

        async def no_store_send(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": [
                    (name, value) for name, value in message.get("headers", []) if name.lower() != b"cache-control"
                ] + [(b"cache-control", b"no-store")]}
            await send(message)

        return await self.app(scope, bounded_receive, no_store_send)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _valid_grant(grant: LocalOllamaGrant, now: datetime, *, allow_pending: bool = False) -> bool:
    if not grant.session_hash:
        return False  # Legacy credentials and unconsumed pairing codes fail closed.
    if grant.approved_at is None:
        return allow_pending and grant.pairing_expires_at is not None and as_utc(grant.pairing_expires_at) > now
    return (grant.expires_at is not None and as_utc(grant.expires_at) > now
            and as_utc(grant.last_seen_at or grant.approved_at) + IDLE_TTL > now)


def _bearer_hash(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[7:].strip()
    if len(token) < 32 or len(token) > 256:
        return None
    return _hash(token)


def resolve_worker_user(request: Request, *, allow_pending: bool = False) -> User | None:
    token_hash = _bearer_hash(request)
    if token_hash is None:
        return None
    with session() as s:
        # noscope: the bearer hash is the authentication primitive; no tenant is known yet.
        grant = s.exec(select(LocalOllamaGrant).where(LocalOllamaGrant.session_hash == token_hash)).first()
        if grant is None or not _valid_grant(grant, utc_now(), allow_pending=allow_pending):
            return None
        user = s.get(User, grant.user_id)
        if user is None or user.disabled:
            return None
        s.expunge(user)
        request.state.local_worker_grant = grant.token_hash
        return user


def require_worker_user(request: Request) -> User:
    user = getattr(request.state, "local_worker_user", None) or resolve_worker_user(request)
    if user is None:
        raise HTTPException(401, "local Ollama worker is not connected")
    request.state.user_id = user.id
    return user


def require_site_user(request: Request, user: User = Depends(require_user)) -> User:
    """SameSite cookies alone do not stop requests from an untrusted subdomain."""
    origin = request.headers.get("origin")
    if origin is not None:
        allowed = {str(request.base_url).rstrip("/").lower()}
        allowed.update(value.strip().rstrip("/").lower() for value in os.environ.get(
            "ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000",
        ).split(",") if value.strip() not in {"*", "null", ""})
        if origin.rstrip("/").lower() not in allowed:
            raise HTTPException(403, "worker approval requires a trusted site origin")
    return user


def worker_online(user_id: int) -> bool:
    now = utc_now()
    cutoff = (now - ONLINE_FOR).replace(tzinfo=None)
    with session() as s:
        grants = s.exec(owned(select(LocalOllamaGrant), LocalOllamaGrant, user_id).where(
            LocalOllamaGrant.last_seen_at >= cutoff
        )).all()
        return any(_valid_grant(grant, now) for grant in grants)


def worker_models(user_id: int) -> list[str]:
    """Installed models reported by online workers belonging to this user."""
    now = utc_now()
    cutoff = (now - ONLINE_FOR).replace(tzinfo=None)
    with session() as s:
        grants = s.exec(owned(select(LocalOllamaGrant), LocalOllamaGrant, user_id).where(
            LocalOllamaGrant.last_seen_at >= cutoff
        )).all()
        grants = [g for g in grants if _valid_grant(g, now)]
        if not grants:
            raise HTTPException(503, "Start your local Ollama worker on your computer, then retry.")
        inventories = [g.models_json for g in grants if g.models_json is not None]
    if not inventories:
        raise HTTPException(409, "Download the updated local Ollama worker and restart it to load installed models.")
    return sorted({model for inventory in inventories for model in json.loads(inventory)}, key=str.casefold)


@site_router.get("/status")
def status(response: Response, user: User = Depends(require_user)) -> dict:
    now = utc_now()
    cutoff = now - ONLINE_FOR
    with session() as s:
        grants = s.exec(owned(select(LocalOllamaGrant), LocalOllamaGrant, user).order_by(
            LocalOllamaGrant.created_at.desc()
        )).all()
        rows = [
            {"id": g.token_hash, "created_at": g.created_at.isoformat(),
             "last_seen_at": g.last_seen_at.isoformat() if g.last_seen_at else None,
             "online": _valid_grant(g, now) and g.last_seen_at is not None and as_utc(g.last_seen_at) >= cutoff,
             "state": ("approved" if _valid_grant(g, now) else "pending" if _valid_grant(g, now, allow_pending=True)
                       else "pairing" if not g.session_hash and g.pairing_expires_at and as_utc(g.pairing_expires_at) > now
                       else "expired"),
             "verification_code": g.session_hash[:12] if g.session_hash and g.approved_at is None else None,
             "expires_at": as_utc(g.expires_at).isoformat() if g.expires_at else None}
            for g in grants
        ]
    response.headers["Cache-Control"] = "no-store"
    return {"online": any(g["online"] for g in rows), "workers": rows}


@site_router.post("/tokens")
@limiter.limit("5/minute")
def create_token(request: Request, response: Response, user: User = Depends(require_site_user)) -> dict:
    token = secrets.token_urlsafe(48)
    expires = utc_now() + PAIRING_TTL
    with session() as s:
        existing = s.exec(owned(select(LocalOllamaGrant), LocalOllamaGrant, user)).all()
        for grant in existing[:]:
            if not _valid_grant(grant, utc_now(), allow_pending=True) and (
                    grant.session_hash or grant.pairing_expires_at is None or as_utc(grant.pairing_expires_at) <= utc_now()):
                s.delete(grant)
                existing.remove(grant)
        if len(existing) >= 5:
            raise HTTPException(409, "disconnect an old Ollama worker before adding another")
        s.add(LocalOllamaGrant(token_hash=_hash(token), user_id=user.id, pairing_expires_at=expires))
        s.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"token": token, "expires_at": expires.isoformat()}


@pair_router.post("/connect")
@limiter.limit("10/minute", key_func=get_remote_address)
def connect_worker(body: EmptyBody, request: Request, response: Response) -> dict:
    token_hash = _bearer_hash(request)
    session_token = secrets.token_urlsafe(48)
    now = utc_now()
    with session() as s:
        # noscope: a one-time pairing hash identifies the grant before we know its owner.
        grant = s.get(LocalOllamaGrant, token_hash) if token_hash else None
        if (grant is None or grant.session_hash or grant.pairing_expires_at is None
                or as_utc(grant.pairing_expires_at) <= now):
            raise HTTPException(401, "pairing code expired or already used")
        user = s.get(User, grant.user_id)
        if user is None or user.disabled:
            raise HTTPException(401, "pairing code expired or already used")
        claimed = s.exec(update(LocalOllamaGrant).where(
            LocalOllamaGrant.token_hash == token_hash, LocalOllamaGrant.user_id == user.id,
            LocalOllamaGrant.session_hash.is_(None), LocalOllamaGrant.pairing_expires_at > now,
        ).values(session_hash=_hash(session_token), pairing_expires_at=now + PAIRING_TTL)
          .execution_options(synchronize_session=False))
        if not claimed.rowcount:
            raise HTTPException(401, "pairing code expired or already used")
        s.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"token": session_token, "verification_code": _hash(session_token)[:12]}


@pair_router.get("/approval")
@limiter.limit("20/minute")
def worker_approval(request: Request, response: Response, user: User = Depends(require_worker_user)) -> dict:
    if resolve_worker_user(request, allow_pending=True) is None:
        raise HTTPException(401, "pairing or session expired; pair again")
    with session() as s:
        grant = find_owned(s, LocalOllamaGrant, request.state.local_worker_grant, user)
        if grant is None or not _valid_grant(grant, utc_now(), allow_pending=True):
            raise HTTPException(401, "pairing or session expired; pair again")
        response.headers["Cache-Control"] = "no-store"
        return {"approved": grant.approved_at is not None,
                "expires_at": as_utc(grant.expires_at).isoformat() if grant.expires_at else None}


class ApprovalBody(BaseModel):
    model_config = {"extra": "forbid"}
    verification_code: str = Field(min_length=12, max_length=12, pattern=r"^[a-fA-F0-9]{12}$")


@site_router.post("/tokens/{token_hash}/approve")
def approve_worker(token_hash: str, body: ApprovalBody, user: User = Depends(require_site_user)) -> dict:
    now = utc_now()
    with session() as s:
        grant = s.exec(owned(select(LocalOllamaGrant), LocalOllamaGrant, user).where(
            LocalOllamaGrant.token_hash == token_hash
        ).with_for_update()).first()
        if grant is None:
            raise HTTPException(404, "worker connection not found")
        if grant.approved_at is not None or not _valid_grant(grant, now, allow_pending=True):
            raise HTTPException(409, "pairing code expired or already approved")
        if not secrets.compare_digest(grant.session_hash[:12], body.verification_code.lower()):
            raise HTTPException(403, "verification code does not match the worker")
        grant.approved_at = now
        grant.expires_at = now + SESSION_TTL
        s.add(grant)
        s.commit()
    return {"ok": True}


@site_router.delete("/tokens/{token_hash}")
def revoke_token(token_hash: str, user: User = Depends(require_site_user)) -> dict:
    with session() as s:
        grant = get_owned(s, LocalOllamaGrant, token_hash, user,
                          detail="worker connection not found")
        s.delete(grant)
        s.exec(update(LocalOllamaTask).where(
            LocalOllamaTask.user_id == user.id, LocalOllamaTask.worker_grant_hash == token_hash,
            LocalOllamaTask.status == "leased",
        ).values(status="error", error="Worker disconnected", payload="", lease_hash="")
          .execution_options(synchronize_session=False))
        s.commit()
    return {"ok": True}


@site_router.get("/download")
def download_worker() -> FileResponse:
    return FileResponse(
        WORKER_SCRIPT, filename="applination-ollama-worker.py",
        media_type="text/x-python", headers={"Cache-Control": "no-store"},
    )


def _touch_grant(grant_hash: str, user_id: int) -> None:
    with session() as s:
        grant = _active_grant(s, grant_hash, user_id)
        # Legacy activity/lease columns store UTC without a timezone.
        grant.last_seen_at = utc_now().replace(tzinfo=None)
        s.add(grant)
        s.commit()


@worker_router.get("/ping")
@limiter.shared_limit(WORKER_LIMIT, scope="ollama-worker")
def worker_ping(request: Request, user: User = Depends(require_worker_user)) -> dict:
    _touch_grant(request.state.local_worker_grant, user.id)
    return {"ok": True}


def revoke_all_worker_sessions(s, user_id: int) -> None:
    """Password changes invalidate pairing codes and workers for this account."""
    grants = s.exec(owned(select(LocalOllamaGrant), LocalOllamaGrant, user_id).with_for_update()).all()
    for grant in grants:
        s.delete(grant)
    s.exec(update(LocalOllamaTask).where(
        LocalOllamaTask.user_id == user_id, LocalOllamaTask.status == "leased",
    ).values(status="error", error="Worker disconnected after password change", payload="", lease_hash="")
      .execution_options(synchronize_session=False))
    s.commit()


def _active_grant(s, grant_hash: str, user_id: int) -> LocalOllamaGrant:
    grant = s.exec(owned(select(LocalOllamaGrant), LocalOllamaGrant, user_id).where(
        LocalOllamaGrant.token_hash == grant_hash
    ).with_for_update()).first()
    user = s.get(User, user_id)
    if grant is None or not _valid_grant(grant, utc_now()) or user is None or user.disabled:
        raise HTTPException(401, "worker session expired or revoked; pair again")
    return grant


class ModelsBody(BaseModel):
    model_config = {"extra": "forbid"}
    models: list[str] = Field(max_length=500)

    @field_validator("models")
    @classmethod
    def validate_models(cls, models: list[str]) -> list[str]:
        if any(not model or len(model) > 200 or any(ch.isspace() or ord(ch) < 32 for ch in model)
               for model in models):
            raise ValueError("Invalid Ollama model ID")
        return sorted(set(models), key=str.casefold)


@worker_router.post("/models")
@limiter.shared_limit(WORKER_LIMIT, scope="ollama-worker")
def report_models(body: ModelsBody, request: Request, user: User = Depends(require_worker_user)) -> dict:
    with session() as s:
        grant = _active_grant(s, request.state.local_worker_grant, user.id)
        grant.models_json = json.dumps(body.models)
        grant.last_seen_at = utc_now().replace(tzinfo=None)
        s.add(grant)
        s.commit()
    return {"ok": True}


def _claim(user_id: int, grant_hash: str) -> dict | None:
    now = utc_now().replace(tzinfo=None)
    with session() as s:
        _active_grant(s, grant_hash, user_id)
        candidates = s.exec(owned(select(LocalOllamaTask), LocalOllamaTask, user_id).where(
            or_(LocalOllamaTask.status == "pending", (
                (LocalOllamaTask.status == "leased") &
                (LocalOllamaTask.lease_until <= now)
            ))
        ).order_by(LocalOllamaTask.created_at).limit(3)).all()
        for task in candidates:
            lease = secrets.token_urlsafe(32)
            claimed = s.exec(update(LocalOllamaTask).where(
                LocalOllamaTask.id == task.id,
                LocalOllamaTask.user_id == user_id,
                or_(LocalOllamaTask.status == "pending", (
                    (LocalOllamaTask.status == "leased") &
                    (LocalOllamaTask.lease_until <= now)
                )),
            ).values(status="leased", lease_hash=_hash(lease),
                     lease_until=now + LEASE_FOR, worker_grant_hash=grant_hash)
              .execution_options(synchronize_session=False))
            if claimed.rowcount:
                answer = {"id": task.id, "lease": lease, "payload": json.loads(task.payload)}
                s.commit()
                return answer
    return None


@worker_router.get("/next")
@limiter.shared_limit(WORKER_LIMIT, scope="ollama-worker")
async def next_task(request: Request, user: User = Depends(require_worker_user)) -> dict:
    grant_hash = request.state.local_worker_grant
    _touch_grant(grant_hash, user.id)
    for _ in range(20):
        task = _claim(user.id, grant_hash)
        if task is not None:
            return {"task": task}
        await asyncio.sleep(0.5)
    return {"task": None}


class LeaseBody(BaseModel):
    model_config = {"extra": "forbid"}
    lease: str = Field(min_length=32, max_length=256)


@worker_router.post("/tasks/{task_id}/heartbeat")
@limiter.shared_limit(WORKER_LIMIT, scope="ollama-worker")
def heartbeat(task_id: str, body: LeaseBody, request: Request,
              user: User = Depends(require_worker_user)) -> dict:
    _touch_grant(request.state.local_worker_grant, user.id)
    with session() as s:
        _active_grant(s, request.state.local_worker_grant, user.id)
        changed = s.exec(update(LocalOllamaTask).where(
            LocalOllamaTask.id == task_id, LocalOllamaTask.user_id == user.id,
            LocalOllamaTask.status == "leased", LocalOllamaTask.lease_hash == _hash(body.lease),
            LocalOllamaTask.worker_grant_hash == request.state.local_worker_grant,
            LocalOllamaTask.lease_until > utc_now().replace(tzinfo=None),
        ).values(lease_until=utc_now().replace(tzinfo=None) + LEASE_FOR).execution_options(synchronize_session=False))
        if not changed.rowcount:
            raise HTTPException(404, "model request is no longer active")
        s.commit()
    return {"ok": True}


class ResultBody(LeaseBody):
    content: str = Field(default="", max_length=200_000)
    error: str = Field(default="", max_length=1000)


@worker_router.post("/tasks/{task_id}/result")
@limiter.shared_limit(WORKER_LIMIT, scope="ollama-worker")
def submit_result(task_id: str, body: ResultBody, request: Request,
                  user: User = Depends(require_worker_user)) -> dict:
    _touch_grant(request.state.local_worker_grant, user.id)
    with session() as s:
        _active_grant(s, request.state.local_worker_grant, user.id)
        task = find_owned(s, LocalOllamaTask, task_id, user)
        if (task is None or task.status != "leased" or task.lease_hash != _hash(body.lease)
                or task.worker_grant_hash != request.state.local_worker_grant
                or task.lease_until is None or as_utc(task.lease_until) <= utc_now()):
            raise HTTPException(404, "model request is no longer active")
        if not body.error and json.loads(task.payload).get("format_json"):
            try:
                parsed = json.loads(body.content)
            except (ValueError, RecursionError):
                raise HTTPException(422, "worker response must be valid JSON") from None
            if not isinstance(parsed, dict):
                raise HTTPException(422, "worker response must be a JSON object")
        changed = s.exec(update(LocalOllamaTask).where(
            LocalOllamaTask.id == task_id, LocalOllamaTask.user_id == user.id,
            LocalOllamaTask.status == "leased", LocalOllamaTask.lease_hash == _hash(body.lease),
            LocalOllamaTask.worker_grant_hash == request.state.local_worker_grant,
            LocalOllamaTask.lease_until > utc_now().replace(tzinfo=None),
        ).values(status="error" if body.error else "done", error=body.error,
                 result="" if body.error else body.content, payload="", lease_hash="")
          .execution_options(synchronize_session=False))
        if not changed.rowcount:
            raise HTTPException(404, "model request is no longer active")
        s.commit()
    return {"ok": True}


def run_inference(user_id: int, *, model: str, system: str, user: str,
                  max_tokens: int, format_json: bool) -> str:
    """Synchronous LLMProvider boundary used by all existing server workflows."""
    if not worker_online(user_id):
        raise RuntimeError("Your local Ollama worker is offline. Start it on your computer, then retry.")
    task_id = uuid.uuid4().hex
    payload = json.dumps({
        "model": model, "system": system, "user": user,
        "max_tokens": max_tokens, "format_json": format_json,
    })
    with session() as s:
        s.add(LocalOllamaTask(id=task_id, user_id=user_id, payload=payload))
        s.commit()
    deadline = time.monotonic() + CALL_TIMEOUT
    next_presence_check = time.monotonic() + 5
    try:
        while time.monotonic() < deadline:
            with session() as s:
                task = find_owned(s, LocalOllamaTask, task_id, user_id)
                if task is None:
                    raise RuntimeError("Local Ollama request disappeared")
                if task.status == "done":
                    return task.result
                if task.status == "error":
                    raise RuntimeError(f"Local Ollama: {task.error}")
            if time.monotonic() >= next_presence_check:
                if not worker_online(user_id):
                    raise RuntimeError("Your local Ollama worker disconnected. Start it, then retry.")
                next_presence_check = time.monotonic() + 5
            time.sleep(0.5)
        raise RuntimeError("Local Ollama timed out. Check that the worker and model are still running.")
    finally:
        with session() as s:
            task = find_owned(s, LocalOllamaTask, task_id, user_id)
            if task is not None:
                s.delete(task)
                s.commit()


def cleanup_stale_tasks() -> None:
    """Drop prompts orphaned by an API restart after callers have timed out."""
    cutoff = datetime.utcnow() - timedelta(seconds=CALL_TIMEOUT + 120)
    with session() as s:
        # noscope: periodic janitor removes expired tasks across all accounts.
        s.exec(delete(LocalOllamaTask).where(LocalOllamaTask.created_at < cutoff))
        s.commit()
