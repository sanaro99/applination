"""Authenticated outbound bridge from hosted runs to a user's local Ollama.

Only the user's worker contacts localhost. Pending prompts live briefly in the
database so a server restart or another API process does not change ownership.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, or_, update
from sqlmodel import select

from .auth import require_user
from .db import LocalOllamaGrant, LocalOllamaTask, User, session
from .scoping import find_owned, get_owned, owned

site_router = APIRouter(prefix="/api/local-ollama", tags=["local-ollama"])
worker_router = APIRouter(prefix="/api/local-ollama/worker", tags=["local-ollama-worker"])

ONLINE_FOR = timedelta(seconds=35)
LEASE_FOR = timedelta(minutes=2)
CALL_TIMEOUT = 660
WORKER_SCRIPT = Path(__file__).resolve().parent.parent / "local_ollama_worker.py"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def resolve_worker_user(request: Request) -> User | None:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[7:].strip()
    if len(token) < 32 or len(token) > 256:
        return None
    with session() as s:
        # noscope: the bearer hash is the authentication primitive; no tenant is known yet.
        grant = s.get(LocalOllamaGrant, _hash(token))
        if grant is None:
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


def worker_online(user_id: int) -> bool:
    cutoff = datetime.utcnow() - ONLINE_FOR
    with session() as s:
        grant = s.exec(owned(select(LocalOllamaGrant), LocalOllamaGrant, user_id).where(
            LocalOllamaGrant.last_seen_at >= cutoff
        )).first()
        return grant is not None


def worker_models(user_id: int) -> list[str]:
    """Installed models reported by online workers belonging to this user."""
    cutoff = datetime.utcnow() - ONLINE_FOR
    with session() as s:
        grants = s.exec(owned(select(LocalOllamaGrant), LocalOllamaGrant, user_id).where(
            LocalOllamaGrant.last_seen_at >= cutoff
        )).all()
        if not grants:
            raise HTTPException(503, "Start your local Ollama worker on your computer, then retry.")
        inventories = [g.models_json for g in grants if g.models_json is not None]
    if not inventories:
        raise HTTPException(409, "Download the updated local Ollama worker and restart it to load installed models.")
    return sorted({model for inventory in inventories for model in json.loads(inventory)}, key=str.casefold)


@site_router.get("/status")
def status(user: User = Depends(require_user)) -> dict:
    cutoff = datetime.utcnow() - ONLINE_FOR
    with session() as s:
        grants = s.exec(owned(select(LocalOllamaGrant), LocalOllamaGrant, user).order_by(
            LocalOllamaGrant.created_at.desc()
        )).all()
        rows = [
            {"id": g.token_hash, "created_at": g.created_at.isoformat(),
             "last_seen_at": g.last_seen_at.isoformat() if g.last_seen_at else None,
             "online": g.last_seen_at is not None and g.last_seen_at >= cutoff}
            for g in grants
        ]
    return {"online": any(g["online"] for g in rows), "workers": rows}


@site_router.post("/tokens")
def create_token(response: Response, user: User = Depends(require_user)) -> dict:
    token = secrets.token_urlsafe(48)
    with session() as s:
        existing = s.exec(owned(select(LocalOllamaGrant), LocalOllamaGrant, user)).all()
        if len(existing) >= 5:
            raise HTTPException(409, "disconnect an old Ollama worker before adding another")
        s.add(LocalOllamaGrant(token_hash=_hash(token), user_id=user.id))
        s.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"token": token}


@site_router.delete("/tokens/{token_hash}")
def revoke_token(token_hash: str, user: User = Depends(require_user)) -> dict:
    with session() as s:
        grant = get_owned(s, LocalOllamaGrant, token_hash, user,
                          detail="worker connection not found")
        s.delete(grant)
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
        grant = find_owned(s, LocalOllamaGrant, grant_hash, user_id)
        if grant is None:
            raise HTTPException(401, "worker connection was revoked")
        grant.last_seen_at = datetime.utcnow()
        s.add(grant)
        s.commit()


@worker_router.get("/ping")
def worker_ping(request: Request, user: User = Depends(require_worker_user)) -> dict:
    _touch_grant(request.state.local_worker_grant, user.id)
    return {"ok": True}


class ModelsBody(BaseModel):
    models: list[str] = Field(max_length=500)

    @field_validator("models")
    @classmethod
    def validate_models(cls, models: list[str]) -> list[str]:
        if any(not model or len(model) > 200 or any(ch.isspace() or ord(ch) < 32 for ch in model)
               for model in models):
            raise ValueError("Invalid Ollama model ID")
        return sorted(set(models), key=str.casefold)


@worker_router.post("/models")
def report_models(body: ModelsBody, request: Request, user: User = Depends(require_worker_user)) -> dict:
    with session() as s:
        grant = find_owned(s, LocalOllamaGrant, request.state.local_worker_grant, user)
        if grant is None:
            raise HTTPException(401, "worker connection was revoked")
        grant.models_json = json.dumps(body.models)
        grant.last_seen_at = datetime.utcnow()
        s.add(grant)
        s.commit()
    return {"ok": True}


def _claim(user_id: int) -> dict | None:
    now = datetime.utcnow()
    with session() as s:
        candidates = s.exec(owned(select(LocalOllamaTask), LocalOllamaTask, user_id).where(
            or_(LocalOllamaTask.status == "pending", (
                (LocalOllamaTask.status == "leased") &
                (LocalOllamaTask.lease_until < now)
            ))
        ).order_by(LocalOllamaTask.created_at).limit(3)).all()
        for task in candidates:
            lease = secrets.token_urlsafe(32)
            claimed = s.exec(update(LocalOllamaTask).where(
                LocalOllamaTask.id == task.id,
                LocalOllamaTask.user_id == user_id,
                or_(LocalOllamaTask.status == "pending", (
                    (LocalOllamaTask.status == "leased") &
                    (LocalOllamaTask.lease_until < now)
                )),
            ).values(status="leased", lease_hash=_hash(lease),
                     lease_until=now + LEASE_FOR))
            s.commit()
            if claimed.rowcount:
                return {"id": task.id, "lease": lease, "payload": json.loads(task.payload)}
    return None


@worker_router.get("/next")
async def next_task(request: Request, user: User = Depends(require_worker_user)) -> dict:
    grant_hash = request.state.local_worker_grant
    _touch_grant(grant_hash, user.id)
    for _ in range(20):
        task = _claim(user.id)
        if task is not None:
            return {"task": task}
        await asyncio.sleep(0.5)
    return {"task": None}


class LeaseBody(BaseModel):
    lease: str = Field(min_length=32, max_length=256)


@worker_router.post("/tasks/{task_id}/heartbeat")
def heartbeat(task_id: str, body: LeaseBody, request: Request,
              user: User = Depends(require_worker_user)) -> dict:
    _touch_grant(request.state.local_worker_grant, user.id)
    with session() as s:
        task = find_owned(s, LocalOllamaTask, task_id, user)
        if task is None or task.status != "leased" or task.lease_hash != _hash(body.lease):
            raise HTTPException(404, "model request is no longer active")
        task.lease_until = datetime.utcnow() + LEASE_FOR
        s.add(task)
        s.commit()
    return {"ok": True}


class ResultBody(LeaseBody):
    content: str = Field(default="", max_length=1_000_000)
    error: str = Field(default="", max_length=1000)


@worker_router.post("/tasks/{task_id}/result")
def submit_result(task_id: str, body: ResultBody, request: Request,
                  user: User = Depends(require_worker_user)) -> dict:
    _touch_grant(request.state.local_worker_grant, user.id)
    with session() as s:
        task = find_owned(s, LocalOllamaTask, task_id, user)
        if task is None or task.status != "leased" or task.lease_hash != _hash(body.lease):
            raise HTTPException(404, "model request is no longer active")
        task.status = "error" if body.error else "done"
        task.error = body.error
        task.result = body.content
        task.payload = ""  # release prompt as soon as inference finishes
        task.lease_hash = ""
        s.add(task)
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
