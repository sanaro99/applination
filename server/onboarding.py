"""Onboarding / first-run setup endpoints.

A brand-new user has no usable config or master data. These endpoints let the
web wizard (1) detect what is still missing, (2) import a raw resume into the
master-resume format via the LLM, and (3) mark setup complete. Saving config and
master data reuses the existing PUT endpoints in config_api.py; AI authoring of
bio/stories reuses studio.py.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import select

from .config_api import BIO_PATH, RESUME_PATH, STORIES_DIR
from .db import Setting, User, session
from .auth import require_owner, require_user
from .deps import load_config, update_config
from .studio import _call, _resolve_chain

# Owner-only, wholesale. Every endpoint here reads or writes the single global
# config.yaml, which is not per-user until PR 3. Signup is open, so
# without this any account could overwrite the owner's contact details, provider keys and search settings.
#
# Applied at the router rather than per-endpoint so a new endpoint added to this
# file is owner-gated by default rather than by remembering.
router = APIRouter(
    prefix="/api/onboarding", tags=["onboarding"],
    dependencies=[Depends(require_owner)],
)

# /status is the one exception: OnboardingGate polls it on every page load for
# every user, so owner-gating it would 403 non-owners out of the whole app. It
# lives on its own router with only require_user.
status_router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])
log = logging.getLogger("server.onboarding")

# Provider -> env var that can supply its key (mirrors the providers layer).
_PROVIDER_ENV = {
    "claude": "ANTHROPIC_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "nim": "NVIDIA_API_KEY",
}

_PLACEHOLDER_NAMES = {"", "your name"}


def _get_setting(user_id: int, key: str) -> str | None:
    with session() as s:
        # noscope: Setting's primary key IS (user_id, key) — scoped by
        # construction. The onboarding flag is per-user; sharing one row would
        # mean the second user to register lands mid-wizard.
        row = s.get(Setting, (user_id, key))
        return row.value if row else None


def _set_setting(user_id: int, key: str, value: str) -> None:
    with session() as s:
        # noscope: composite primary key (user_id, key).
        row = s.get(Setting, (user_id, key))
        if row:
            row.value = value
        else:
            row = Setting(user_id=user_id, key=key, value=value)
        s.add(row)
        s.commit()


def _provider_ready(llm: dict) -> bool:
    """True if at least one LLM provider can actually be called (key set in
    config or env, or a local Ollama base_url)."""
    for name, env in _PROVIDER_ENV.items():
        block = llm.get(name) or {}
        if str(block.get("api_key") or "").strip() or os.environ.get(env):
            return True
    ollama = llm.get("ollama") or {}
    if str(ollama.get("base_url") or "").strip():
        return True
    return False


def _count_stories() -> int:
    if not STORIES_DIR.exists():
        return 0
    return sum(1 for p in STORIES_DIR.glob("*.md") if not p.name.startswith("_"))


def _compute_status(user_id: int) -> dict:
    cfg = load_config() or {}
    user = cfg.get("user") or {}
    llm = cfg.get("llm") or {}

    name = str(user.get("full_name") or "").strip()
    email = str(user.get("email") or "").strip()
    contact_ok = name.lower() not in _PLACEHOLDER_NAMES and bool(email) and "example.com" not in email
    provider_ok = _provider_ready(llm)
    resume_ok = RESUME_PATH.exists()
    bio_ok = BIO_PATH.exists()
    stories = _count_stories()

    marked = _get_setting(user_id, "onboarded") == "1"
    can_run = contact_ok and provider_ok and resume_ok
    return {
        "onboarded": marked or can_run,
        "marked_complete": marked,
        "can_run": can_run,
        "steps": {
            "provider": provider_ok,
            "contact": contact_ok,
            "resume": resume_ok,
            "bio": bio_ok,
            "stories": stories,
        },
    }


@status_router.get("/status")
def status(user: User = Depends(require_user)) -> dict:
    """Setup state for the onboarding gate.

    Non-owners get a fixed "nothing to do" answer rather than the real one.
    Onboarding configures the single global install, which only the owner can
    do until PR 3 — and the real payload would otherwise report the owner's
    setup progress to every account that signs up.
    """
    if not user.is_owner:
        return {
            "onboarded": True,
            "marked_complete": True,
            "can_run": False,
            "steps": {
                "provider": False,
                "contact": False,
                "resume": False,
                "bio": False,
                "stories": 0,
            },
        }
    return _compute_status(user.id)


@router.post("/complete")
def complete(user: User = Depends(require_owner)) -> dict:
    _set_setting(user.id, "onboarded", "1")
    return {"ok": True, **_compute_status(user.id)}


@router.post("/reset")
def reset(user: User = Depends(require_owner)) -> dict:
    """Re-open onboarding (does not delete any data)."""
    _set_setting(user.id, "onboarded", "0")
    return {"ok": True, **_compute_status(user.id)}


# --- Structured config writers (preserve comments via ruamel) ----------------

class UserBody(BaseModel):
    full_name: str
    email: str
    phone: str = ""
    location_city: str = ""
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""


@router.put("/user")
def set_user(body: UserBody, user: User = Depends(require_owner)) -> dict:
    def mut(data: dict) -> None:
        user = data.get("user")
        if user is None:
            user = {}
            data["user"] = user
        for k, v in body.model_dump().items():
            user[k] = v
    update_config(mut)
    return {"ok": True, **_compute_status(user.id)}


class ProviderBody(BaseModel):
    provider: str
    api_key: str = ""
    model: str | None = None
    base_url: str | None = None
    make_primary: bool = True


@router.put("/provider")
def set_provider(
    body: ProviderBody, user: User = Depends(require_owner)
) -> dict:
    name = body.provider.strip().lower()
    if not name:
        raise HTTPException(400, "provider is required")

    def mut(data: dict) -> None:
        llm = data.get("llm")
        if llm is None:
            llm = {}
            data["llm"] = llm
        block = llm.get(name)
        if block is None:
            block = {}
            llm[name] = block
        if body.api_key:
            block["api_key"] = body.api_key
        if body.model:
            block["model"] = body.model
        if body.base_url:
            block["base_url"] = body.base_url
        if body.make_primary:
            llm["primary"] = name
    update_config(mut)
    return {"ok": True, **_compute_status(user.id)}


class SearchBody(BaseModel):
    keywords: list[str]
    remote_ok: bool = True
    onsite_cities: list[str] = []
    countries: list[str] = ["us"]
    max_jobs_per_day: int | None = None
    min_match_score: int | None = None


@router.put("/search")
def set_search(
    body: SearchBody, user: User = Depends(require_owner)
) -> dict:
    def mut(data: dict) -> None:
        search = data.get("search")
        if search is None:
            search = {}
            data["search"] = search
        search["keywords"] = [k for k in body.keywords if k.strip()]
        search["remote_ok"] = body.remote_ok
        search["onsite_cities"] = body.onsite_cities
        search["countries"] = body.countries
        if body.max_jobs_per_day is not None:
            search["max_jobs_per_day"] = body.max_jobs_per_day
        if body.min_match_score is not None:
            search["min_match_score"] = body.min_match_score
    update_config(mut)
    return {"ok": True, **_compute_status(user.id)}


# --- Resume import -----------------------------------------------------------

def _extract_text(filename: str, data: bytes) -> str:
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    if ext == "pdf":
        try:
            from pypdf import PdfReader
        except ImportError as e:  # noqa: BLE001
            raise HTTPException(
                400,
                "PDF support needs the 'pypdf' package (pip install pypdf). "
                "Alternatively paste your resume text instead of uploading a PDF.",
            ) from e
        import io
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    if ext == "docx":
        try:
            import docx  # python-docx
        except ImportError as e:  # noqa: BLE001
            raise HTTPException(400, "DOCX support needs python-docx.") from e
        import io
        document = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in document.paragraphs).strip()
    # Fallback: treat as plain text.
    try:
        return data.decode("utf-8", errors="ignore").strip()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"could not read file: {e}") from e


class ImportTextBody(BaseModel):
    text: str
    provider: str | None = None


def _do_import(raw_text: str, provider: str | None) -> dict:
    if len(raw_text.strip()) < 40:
        raise HTTPException(400, "resume text is too short to import")
    from src.content_studio import import_resume, master_resume_to_yaml

    chain = _resolve_chain(provider)
    data = _call(chain, lambda p: import_resume(raw_text, provider=p))
    return {"text": master_resume_to_yaml(data), "fields": data}


@router.post("/resume-import")
async def resume_import(
    file: UploadFile | None = File(default=None),
) -> dict:
    """Multipart upload (PDF/DOCX/TXT) -> extracted-text -> structured master
    resume YAML (preview; the wizard saves via PUT /api/master-data/resume)."""
    if file is None:
        raise HTTPException(400, "no file uploaded")
    data = await file.read()
    text = _extract_text(file.filename or "resume", data)
    return _do_import(text, None)


@router.post("/resume-import-text")
def resume_import_text(body: ImportTextBody) -> dict:
    """Same as resume-import but from pasted text (and optional provider pick)."""
    return _do_import(body.text, body.provider)
