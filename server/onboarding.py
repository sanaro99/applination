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

from .db import Setting, User, session
from .auth import require_user
from .deps import load_config, paths_for, update_config
from .studio import _call, _resolve_chain
from .user_secrets import SECRET_PATHS, secret_names

# Per-user as of PR 3. Each account onboards its own config.yaml and
# master_data/, so there is nothing here for one user to reach in another's
# setup — and the /status split PR 2 needed (owner sees the truth, everyone else
# a stub) is gone with it.
router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])
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


def _provider_ready(llm: dict, user_id: int) -> bool:
    """True if at least one LLM provider can actually be called.

    ``load_config`` has already merged this user's stored keys into ``llm``, so
    a plain check of the config covers BYOK. The stored-name check behind it
    catches the case where the Fernet key is missing or rotated: the secret
    exists but could not be decrypted, and reporting "no provider" would send
    the user back through the wizard to re-enter a key that is already there.

    The env-var fallback only counts when ALLOW_ENV_API_KEYS is on. Otherwise
    the providers layer refuses to use it, and reporting the user as ready would
    be a lie that surfaces as a provider auth error mid-run.
    """
    from src.providers import env_api_keys_allowed

    allow_env = env_api_keys_allowed()
    for name, env in _PROVIDER_ENV.items():
        block = llm.get(name) or {}
        if str(block.get("api_key") or "").strip():
            return True
        if allow_env and os.environ.get(env):
            return True
    ollama = llm.get("ollama") or {}
    if str(ollama.get("base_url") or "").strip():
        return True
    stored = set(secret_names(user_id))
    return any(p in stored for p in SECRET_PATHS if p.endswith(".api_key"))


def _count_stories(user: User) -> int:
    stories_dir = paths_for(user).stories_dir
    if not stories_dir.exists():
        return 0
    return sum(1 for p in stories_dir.glob("*.md") if not p.name.startswith("_"))


def _compute_status(user: User) -> dict:
    user_id = user.id
    cfg = load_config(user) or {}
    paths = paths_for(user)
    contact = cfg.get("user") or {}
    llm = cfg.get("llm") or {}

    name = str(contact.get("full_name") or "").strip()
    email = str(contact.get("email") or "").strip()
    contact_ok = name.lower() not in _PLACEHOLDER_NAMES and bool(email) and "example.com" not in email
    provider_ok = _provider_ready(llm, user_id)
    resume_ok = paths.resume_path.exists()
    bio_ok = paths.bio_path.exists()
    stories = _count_stories(user)

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


@router.get("/status")
def status(user: User = Depends(require_user)) -> dict:
    """Setup state for the onboarding gate. Every account gets its own real
    answer now, and a fresh signup lands in the wizard rather than inheriting
    somebody else's completed setup."""
    return _compute_status(user)


@router.post("/complete")
def complete(user: User = Depends(require_user)) -> dict:
    _set_setting(user.id, "onboarded", "1")
    return {"ok": True, **_compute_status(user)}


@router.post("/reset")
def reset(user: User = Depends(require_user)) -> dict:
    """Re-open onboarding (does not delete any data)."""
    _set_setting(user.id, "onboarded", "0")
    return {"ok": True, **_compute_status(user)}


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
def set_user(body: UserBody, user: User = Depends(require_user)) -> dict:
    def mut(data: dict) -> None:
        contact = data.get("user")
        if contact is None:
            contact = {}
            data["user"] = contact
        for k, v in body.model_dump().items():
            contact[k] = v
    update_config(user, mut)
    return {"ok": True, **_compute_status(user)}


class ProviderBody(BaseModel):
    provider: str
    api_key: str = ""
    model: str | None = None
    base_url: str | None = None
    make_primary: bool = True


@router.put("/provider")
def set_provider(
    body: ProviderBody, user: User = Depends(require_user)
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
    # update_config diverts block["api_key"] into encrypted UserSecret storage
    # and writes the file with it blanked — the wizard does not have to know.
    update_config(user, mut)
    return {"ok": True, **_compute_status(user)}


class SearchBody(BaseModel):
    keywords: list[str]
    remote_ok: bool = True
    onsite_cities: list[str] = []
    countries: list[str] = ["us"]
    max_jobs_per_day: int | None = None
    min_match_score: int | None = None


@router.put("/search")
def set_search(
    body: SearchBody, user: User = Depends(require_user)
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
    update_config(user, mut)
    return {"ok": True, **_compute_status(user)}


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


def _do_import(user: User, raw_text: str, provider: str | None) -> dict:
    if len(raw_text.strip()) < 40:
        raise HTTPException(400, "resume text is too short to import")
    from src.content_studio import import_resume, master_resume_to_yaml

    chain = _resolve_chain(user, provider)
    data = _call(chain, lambda p: import_resume(raw_text, provider=p))
    return {"text": master_resume_to_yaml(data), "fields": data}


@router.post("/resume-import")
async def resume_import(
    file: UploadFile | None = File(default=None),
    user: User = Depends(require_user),
) -> dict:
    """Multipart upload (PDF/DOCX/TXT) -> extracted-text -> structured master
    resume YAML (preview; the wizard saves via PUT /api/master-data/resume)."""
    if file is None:
        raise HTTPException(400, "no file uploaded")
    data = await file.read()
    text = _extract_text(file.filename or "resume", data)
    return _do_import(user, text, None)


@router.post("/resume-import-text")
def resume_import_text(
    body: ImportTextBody, user: User = Depends(require_user)
) -> dict:
    """Same as resume-import but from pasted text (and optional provider pick)."""
    return _do_import(user, body.text, body.provider)
