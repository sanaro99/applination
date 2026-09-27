"""Narrow, revocable API for the browser autofill extension."""
from __future__ import annotations

import hashlib
import json
import secrets
import uuid
import zipfile
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlmodel import select

from src.master_resume import load_master

from .auth import require_user
from .db import (
    Application, ApplicationStatus, ExtensionDocument, ExtensionGrant,
    ExtensionPairing, Run, RunStatus, SavedAnswer, Setting, User, session,
)
from .deps import load_config, output_root, paths_for
from .limits import LOGIN_LIMIT, LLM_LIMIT, limiter
from .scoping import get_owned, owned
from .user_paths import resolve_within

pair_router = APIRouter(prefix="/api/extension/pair", tags=["extension"])
data_router = APIRouter(prefix="/api/extension/data", tags=["extension"])
download_router = APIRouter(prefix="/api/extension", tags=["extension"])
site_router = APIRouter(prefix="/api/application-profile", tags=["application-profile"])
EXTENSION_DIR = Path(__file__).resolve().parent.parent / "extension"
EXTENSION_PACKAGE_FILES = (
    "manifest.json", "background.js", "content.js", "popup.html", "popup.css", "popup.js",
)
PAIR_TTL = timedelta(minutes=5)
GRANT_TTL = timedelta(days=90)
PROFILE_KEY = "extension.form_profile"
EXTRA_FIELDS = frozenset({
    "address", "city", "state", "postal_code", "country", "website",
    "work_authorization", "sponsorship", "relocation", "salary",
    "preferred_name", "pronouns", "availability", "veteran", "disability",
    "gender", "ethnicity",
})


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normal_url(value: str) -> str:
    try:
        p = urlsplit(value.strip())
        if p.scheme not in ("http", "https") or not p.hostname:
            raise ValueError
        return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/") or "/", p.query, ""))
    except ValueError:
        raise HTTPException(400, "a valid application URL is required") from None


def resolve_extension_user(request: Request) -> User | None:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[7:].strip()
    if len(token) < 32 or len(token) > 256:
        return None
    with session() as s:
        # noscope: the opaque bearer is the authentication primitive; no user is known yet.
        grant = s.get(ExtensionGrant, _hash(token))
        if grant is None or grant.expires_at <= datetime.utcnow():
            return None
        user = s.get(User, grant.user_id)
        if user is None or user.disabled:
            return None
        s.expunge(user)
        if datetime.utcnow() - grant.last_used_at > timedelta(minutes=5):
            grant.last_used_at = datetime.utcnow()
            s.add(grant)
            s.commit()
        return user


def require_extension_user(request: Request) -> User:
    user = getattr(request.state, "extension_user", None) or resolve_extension_user(request)
    if user is None:
        raise HTTPException(401, "extension is not connected")
    request.state.user_id = user.id
    return user


@download_router.get("/download")
def download_extension() -> Response:
    """Package only the reviewed runtime files for signed-in early testers."""
    manifest = json.loads((EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8"))
    archive = BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in EXTENSION_PACKAGE_FILES:
            bundle.write(EXTENSION_DIR / name, arcname=f"applination-extension/{name}")
        bundle.writestr(
            "applination-extension/INSTALL.txt",
            "Unzip this file, then open chrome://extensions in Chrome.\n"
            "Enable Developer mode, choose Load unpacked, and select the extracted "
            "applination-extension folder.\n"
            "Pin Applination Autofill, open it, and choose Connect account.\n"
            "Approve the code on the Applination website where you are signed in.\n",
        )
    filename = f"applination-extension-{manifest['version']}.zip"
    return Response(
        archive.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@pair_router.post("/start")
@limiter.limit(LOGIN_LIMIT)
def start_pair(request: Request) -> dict:
    device_code = secrets.token_urlsafe(32)
    user_code = secrets.token_hex(5).upper()
    with session() as s:
        s.add(ExtensionPairing(
            device_hash=_hash(device_code), user_code_hash=_hash(user_code),
            expires_at=datetime.utcnow() + PAIR_TTL,
        ))
        s.commit()
    return {"device_code": device_code, "user_code": user_code, "expires_in": 300}


class ApproveBody(BaseModel):
    user_code: str


@pair_router.post("/approve")
@limiter.limit(LOGIN_LIMIT)
def approve_pair(request: Request, body: ApproveBody, user: User = Depends(require_user)) -> dict:
    with session() as s:
        # noscope: user_code identifies a pending, unauthenticated pairing.
        pairing = s.exec(select(ExtensionPairing).where(
            ExtensionPairing.user_code_hash == _hash(body.user_code.strip().upper())
        )).first()
        if pairing is None or pairing.expires_at <= datetime.utcnow() or pairing.approved_user_id:
            raise HTTPException(404, "pairing code is invalid or expired")
        pairing.approved_user_id = user.id
        s.add(pairing)
        s.commit()
    return {"ok": True}


class CompleteBody(BaseModel):
    device_code: str


@pair_router.post("/complete")
@limiter.limit("30/minute")
def complete_pair(request: Request, body: CompleteBody) -> dict:
    with session() as s:
        # noscope: the 256-bit device secret identifies the pending pairing.
        pairing = s.get(ExtensionPairing, _hash(body.device_code))
        if pairing is None or pairing.expires_at <= datetime.utcnow():
            raise HTTPException(404, "pairing expired")
        if pairing.approved_user_id is None:
            return {"status": "pending"}
        token = secrets.token_urlsafe(48)
        s.add(ExtensionGrant(
            token_hash=_hash(token), user_id=pairing.approved_user_id,
            expires_at=datetime.utcnow() + GRANT_TTL,
        ))
        s.delete(pairing)
        s.commit()
    return {"status": "connected", "token": token, "expires_in": int(GRANT_TTL.total_seconds())}


@pair_router.get("/grants")
def list_grants(user: User = Depends(require_user)) -> list[dict]:
    with session() as s:
        rows = s.exec(owned(select(ExtensionGrant), ExtensionGrant, user).order_by(
            ExtensionGrant.created_at.desc()
        )).all()
        return [{"id": row.token_hash, "created_at": row.created_at.isoformat(),
                 "last_used_at": row.last_used_at.isoformat()} for row in rows]


@pair_router.delete("/grants/{grant_id}")
def revoke_grant(grant_id: str, user: User = Depends(require_user)) -> dict:
    with session() as s:
        # noscope: exact token hash plus owner check; a mismatch returns 404.
        row = s.get(ExtensionGrant, grant_id)
        if row is None or row.user_id != user.id:
            raise HTTPException(404, "extension connection not found")
        s.delete(row)
        s.commit()
    return {"ok": True}


@data_router.post("/disconnect")
def disconnect(request: Request, user: User = Depends(require_extension_user)) -> dict:
    token = request.headers["authorization"][7:].strip()
    with session() as s:
        # noscope: the token was authenticated above; lookup uses only its hash.
        grant = s.get(ExtensionGrant, _hash(token))
        if grant and grant.user_id == user.id:
            s.delete(grant)
            s.commit()
    return {"ok": True}


def _extra_profile(user: User) -> dict[str, str]:
    with session() as s:
        # noscope: composite primary key includes the authenticated user's id.
        row = s.get(Setting, (user.id, PROFILE_KEY))
        if row is None:
            return {}
        try:
            value = json.loads(row.value)
        except (ValueError, TypeError):
            return {}
    if not isinstance(value, dict):
        return {}
    return {k: str(v) for k, v in value.items() if k in EXTRA_FIELDS and isinstance(v, str)}


@data_router.get("/profile")
def profile(user: User = Depends(require_extension_user)) -> dict:
    return {
        "account": user.email,
        "contact": load_config(user).get("user") or {},
        "resume": load_master(paths_for(user).resume_path),
        "extra": _extra_profile(user),
    }


class ProfileBody(BaseModel):
    extra: dict[str, str]


@data_router.put("/profile")
def update_profile(body: ProfileBody, user: User = Depends(require_extension_user)) -> dict:
    if set(body.extra) - EXTRA_FIELDS or any(len(v) > 500 for v in body.extra.values()):
        raise HTTPException(400, "invalid profile fields")
    with session() as s:
        # noscope: composite primary key includes the authenticated user's id.
        row = s.get(Setting, (user.id, PROFILE_KEY))
        if row is None:
            row = Setting(user_id=user.id, key=PROFILE_KEY)
        row.value = json.dumps({k: v.strip() for k, v in body.extra.items()})
        s.add(row)
        s.commit()
    return {"ok": True}


@data_router.get("/answers")
def answers(user: User = Depends(require_extension_user)) -> list[dict]:
    with session() as s:
        rows = s.exec(owned(select(SavedAnswer), SavedAnswer, user).order_by(
            SavedAnswer.created_at.desc()
        ).limit(300)).all()
        return [{"id": a.id, "prompt": a.prompt, "content": a.content} for a in rows]


class AnswerBody(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)
    content: str = Field(min_length=1, max_length=10000)


@data_router.post("/answers")
def save_answer(body: AnswerBody, user: User = Depends(require_extension_user)) -> dict:
    with session() as s:
        row = SavedAnswer(user_id=user.id, prompt=body.prompt.strip(), content=body.content.strip())
        s.add(row)
        s.commit()
        s.refresh(row)
    return {"id": row.id}


@site_router.get("")
def site_profile(user: User = Depends(require_user)) -> dict:
    return profile(user)


@site_router.put("")
def site_update_profile(body: ProfileBody, user: User = Depends(require_user)) -> dict:
    return update_profile(body, user)


@site_router.get("/answers")
def site_answers(user: User = Depends(require_user)) -> list[dict]:
    return answers(user)


@site_router.post("/answers")
def site_save_answer(body: AnswerBody, user: User = Depends(require_user)) -> dict:
    return save_answer(body, user)


@site_router.delete("/answers/{answer_id}")
def site_delete_answer(answer_id: int, user: User = Depends(require_user)) -> dict:
    with session() as s:
        row = get_owned(s, SavedAnswer, answer_id, user, detail="answer not found")
        s.delete(row)
        s.commit()
    return {"ok": True}


class GenerateAnswerBody(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)
    company: str = Field(default="", max_length=200)
    title: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=15000)
    word_limit: int | None = Field(default=None, ge=20, le=1000)


@data_router.post("/generate-answer")
@limiter.limit(LLM_LIMIT)
def generate_answer(request: Request, body: GenerateAnswerBody, user: User = Depends(require_extension_user)) -> dict:
    from .chat import _run_chain
    from .coach_context import build_essay_prompt, load_profile_bundle, pick_stories
    bundle = load_profile_bundle(paths_for(user))
    job = SimpleNamespace(company=body.company, title=body.title, location="", description=body.description)
    stories = pick_stories(bundle, question=body.prompt, app=job)
    system_prompt, user_prompt = build_essay_prompt(
        bundle, prompt=body.prompt, word_limit=body.word_limit,
        instructions="Answer this job application question accurately.",
        app=job, stories=stories, user=load_config(user).get("user"),
    )
    return {"content": _run_chain(user, system_prompt, user_prompt, task="essay")}


def _document_rows(user: User) -> list[dict]:
    out: list[dict] = []
    with session() as s:
        uploaded = s.exec(owned(select(ExtensionDocument), ExtensionDocument, user).order_by(
            ExtensionDocument.created_at.desc()
        )).all()
        apps = s.exec(owned(select(Application), Application, user).order_by(
            Application.created_at.desc()
        ).limit(100)).all()
    for row in uploaded:
        out.append({"id": f"upload:{row.id}", "kind": row.kind, "label": row.filename})
    for app in apps:
        folder = Path(app.folder_path)
        for kind, stem in (("resume", "resume"), ("cover", "cover_letter")):
            paths = sorted(folder.glob(f"{stem}*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not paths:
                paths = sorted(folder.glob(f"{stem}*.docx"), key=lambda p: p.stat().st_mtime, reverse=True)
            if paths:
                out.append({"id": f"app:{app.id}:{kind}", "kind": kind,
                            "label": f"{app.company} — {app.title}"})
    return out


@data_router.get("/documents")
def documents(user: User = Depends(require_extension_user)) -> list[dict]:
    return _document_rows(user)


@data_router.post("/documents")
async def upload_document(kind: str, file: UploadFile = File(...), user: User = Depends(require_extension_user)) -> dict:
    if kind not in ("resume", "cover"):
        raise HTTPException(400, "kind must be resume or cover")
    filename = Path(file.filename or "").name
    suffix = Path(filename).suffix.lower()
    if suffix not in (".pdf", ".docx"):
        raise HTTPException(400, "upload a PDF or DOCX")
    data = await file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024 or not data:
        raise HTTPException(400, "document must be 10 MB or smaller")
    if suffix == ".pdf" and not data.startswith(b"%PDF-"):
        raise HTTPException(400, "invalid PDF")
    if suffix == ".docx":
        from io import BytesIO
        if not zipfile.is_zipfile(BytesIO(data)):
            raise HTTPException(400, "invalid DOCX")
    name = f"{uuid.uuid4().hex}{suffix}"
    folder = paths_for(user).extension_documents_dir
    folder.mkdir(parents=True, exist_ok=True)
    resolve_within(folder, name).write_bytes(data)
    with session() as s:
        row = ExtensionDocument(user_id=user.id, kind=kind, filename=filename[:200], stored_name=name)
        s.add(row)
        s.commit()
        s.refresh(row)
    return {"id": f"upload:{row.id}", "kind": kind, "label": filename}


@data_router.get("/documents/{document_id:path}")
def document_file(document_id: str, user: User = Depends(require_extension_user)) -> FileResponse:
    parts = document_id.split(":")
    path: Path | None = None
    filename = "document.pdf"
    if len(parts) == 2 and parts[0] == "upload" and parts[1].isdigit():
        with session() as s:
            row = get_owned(s, ExtensionDocument, int(parts[1]), user, detail="document not found")
            path = resolve_within(paths_for(user).extension_documents_dir, row.stored_name)
            filename = row.filename
    elif len(parts) == 3 and parts[0] == "app" and parts[1].isdigit() and parts[2] in ("resume", "cover"):
        with session() as s:
            app = get_owned(s, Application, int(parts[1]), user, detail="document not found")
            folder = Path(app.folder_path)
            stem = "resume" if parts[2] == "resume" else "cover_letter"
            options = sorted(folder.glob(f"{stem}*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not options:
                options = sorted(folder.glob(f"{stem}*.docx"), key=lambda p: p.stat().st_mtime, reverse=True)
            if options:
                path = options[0]
                filename = f"{stem}_{app.company}{path.suffix}"
    if path is None or not path.is_file():
        raise HTTPException(404, "document not found")
    return FileResponse(path, filename=filename, headers={"Cache-Control": "no-store"})


class GenerateResumeBody(BaseModel):
    url: str = Field(max_length=3000)
    company: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    location: str = Field(default="", max_length=200)
    description: str = Field(min_length=1, max_length=15000)


@data_router.post("/generate-resume")
@limiter.limit(LLM_LIMIT)
def generate_resume(request: Request, body: GenerateResumeBody,
                    user: User = Depends(require_extension_user)) -> dict:
    from .runs import MAX_CONCURRENT_RUNS, _active_run_count, _active_run_exists
    from .single_job import GenerateBody, start_generation

    if _active_run_exists(user.id) or _active_run_count() >= MAX_CONCURRENT_RUNS:
        raise HTTPException(409, "a generation run is already active; try again when it finishes")
    payload = GenerateBody(
        url=_normal_url(body.url), company=body.company.strip(), title=body.title.strip(),
        location=body.location.strip(), description=body.description.strip(),
        source="extension", match_reason="opened in browser extension",
    )
    if not payload.company or not payload.title or not payload.description:
        raise HTTPException(400, "company, role, and job description are required")
    return {"run_id": start_generation(payload, user.id)}


@data_router.get("/generate-resume/{run_id}")
def generated_resume(run_id: int, user: User = Depends(require_extension_user)) -> dict:
    with session() as s:
        run = get_owned(s, Run, run_id, user, detail="generation not found")
        app = s.exec(owned(select(Application), Application, user).where(
            Application.run_id == run_id
        )).first()
        return {
            "status": run.status.value,
            "error": run.error or ("No resume was generated" if run.status == RunStatus.done and app is None else ""),
            "application_id": app.id if app else None,
            "resume_id": f"app:{app.id}:resume" if app else None,
            "cover_id": f"app:{app.id}:cover" if app else None,
        }


class TrackBody(BaseModel):
    url: str = Field(max_length=3000)
    company: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    location: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=15000)
    submitted: bool = False
    application_id: int | None = None


@data_router.post("/track")
def track(body: TrackBody, user: User = Depends(require_extension_user)) -> dict:
    url = _normal_url(body.url)
    with session() as s:
        app = get_owned(s, Application, body.application_id, user, detail="application not found") if body.application_id else None
        if app is not None and _normal_url(app.url) != url:
            raise HTTPException(400, "application URL does not match")
        if app is None:
            app = s.exec(owned(select(Application), Application, user).where(
                Application.url == url
            ).order_by(Application.created_at.desc())).first()
        if app is None:
            folder = output_root(user) / date.today().isoformat() / f"extension_{uuid.uuid4().hex[:12]}"
            folder.mkdir(parents=True, exist_ok=True)
            app = Application(user_id=user.id, company=body.company.strip(), title=body.title.strip(),
                              location=body.location.strip(), description=body.description.strip(),
                              url=url, source="extension", folder_path=str(folder),
                              folder_rel=f"{date.today().isoformat()}/{folder.name}")
            s.add(app)
        if body.submitted and app.status == ApplicationStatus.generated:
            app.status = ApplicationStatus.applied
            if app.applied_at is None:
                app.applied_at = datetime.utcnow()
        s.commit()
        s.refresh(app)
        return {"id": app.id, "status": app.status.value}
