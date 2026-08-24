"""Onboarding / first-run setup endpoints.

A brand-new user has no usable config or master data. These endpoints let the
web wizard (1) detect what is still missing, (2) import a raw resume into the
master-resume format via the LLM, and (3) mark setup complete. Saving config and
master data reuses the existing PUT endpoints in config_api.py; AI authoring of
bio/stories reuses studio.py.
"""
from __future__ import annotations

import logging
from functools import lru_cache

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from src.intake_extract import extract_search_terms, extract_threads, load_vocabulary
from src.scrapers.greenhouse_companies import BUILT_IN_SLUGS

from . import intake as intake_store
from .db import Setting, User, session
from .auth import require_user
from .deps import load_config, paths_for, update_config
from .profile_strength import (
    chosen_keywords,
    contact_ok,
    count_stories,
    provider_ready,
)
from .studio import _call, _resolve_chain
from .user_paths import GLOBAL_MASTER_DIR

# Per-user as of PR 3. Each account onboards its own config.yaml and
# master_data/, so there is nothing here for one user to reach in another's
# setup — and the /status split PR 2 needed (owner sees the truth, everyone else
# a stub) is gone with it.
router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])
log = logging.getLogger("server.onboarding")

# The "is this part of the profile done?" predicates live in profile_strength.py
# and are imported above. They used to be duplicated here, which is exactly the
# kind of pair that drifts: the wizard and the dashboard would disagree about
# whether the same account was set up.


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


@lru_cache(maxsize=1)
def _vocabulary() -> frozenset[str]:
    """The committed tag taxonomy, parsed once.

    Safe to cache, unlike per-user paths: this file is global, committed and
    identical for every account.
    """
    index = GLOBAL_MASTER_DIR / "stories" / "_INDEX.md"
    if not index.exists():
        return frozenset()
    return frozenset(load_vocabulary(index.read_text(encoding="utf-8")))


def _intake_corpus(paths) -> tuple[str, str]:
    """Everything the user has told us so far: (typed text, resume text)."""
    told = intake_store.read_notes(paths)
    drafts = intake_store.list_drafts(paths)
    if drafts:
        told = "\n\n".join([told, *(d["body"] for d in drafts)]).strip()
    return told, intake_store.read_parked_resume(paths)


def _compute_status(user: User) -> dict:
    user_id = user.id
    cfg = load_config(user) or {}
    paths = paths_for(user)
    llm = cfg.get("llm") or {}

    contact_ok_ = contact_ok(cfg)
    provider_ok = provider_ready(llm, user_id)
    resume_ok = paths.resume_path.exists()
    bio_ok = paths.bio_path.exists()
    stories = count_stories(paths)

    marked = _get_setting(user_id, "onboarded") == "1"
    can_run = contact_ok_ and provider_ok and resume_ok
    drafts = intake_store.list_drafts(paths)
    return {
        "intake": {
            "notes": bool(intake_store.read_notes(paths).strip()),
            "resume_text": bool(intake_store.read_parked_resume(paths).strip()),
            "drafts": len(drafts),
        },
        "onboarded": marked or can_run,
        "marked_complete": marked,
        "can_run": can_run,
        "steps": {
            "provider": provider_ok,
            "contact": contact_ok_,
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


# --- Intake: raw capture, no LLM ---------------------------------------------
#
# Every endpoint below must work with no provider configured. The journey
# collects material before asking for an API key, so a provider call here would
# break the first chapter for exactly the users it exists to serve.


class NotesBody(BaseModel):
    text: str


@router.post("/intake/notes")
def save_intake_notes(
    body: NotesBody, user: User = Depends(require_user)
) -> dict:
    intake_store.save_notes(paths_for(user), body.text)
    return {"ok": True}


@router.post("/intake/resume")
async def park_intake_resume(
    file: UploadFile | None = File(default=None),
    user: User = Depends(require_user),
) -> dict:
    """Extract text from an uploaded resume and park it — no LLM.

    ``resume-import`` above does the structured extraction and needs a key; this
    one deliberately does not, so the resume is never a wall.
    """
    if file is None:
        raise HTTPException(400, "no file uploaded")
    data = await file.read()
    text = _extract_text(file.filename or "resume", data)
    if not text.strip():
        raise HTTPException(400, "could not read any text from that file")
    intake_store.park_resume(paths_for(user), text)
    return {"ok": True, "chars": len(text)}


class DraftStoryBody(BaseModel):
    title: str
    body: str


@router.post("/intake/story")
def save_intake_story(
    body: DraftStoryBody, user: User = Depends(require_user)
) -> dict:
    if not body.body.strip():
        raise HTTPException(400, "story body is empty")
    path = intake_store.save_draft_story(paths_for(user), body.title, body.body)
    return {"ok": True, "slug": path.stem}


@router.get("/intake/threads")
def intake_threads(user: User = Depends(require_user)) -> dict:
    told, resume_text = _intake_corpus(paths_for(user))
    threads = extract_threads(
        told,
        resume_text,
        vocabulary=set(_vocabulary()),
        companies=BUILT_IN_SLUGS,
    )
    return {"threads": [{"label": t.label, "kind": t.kind} for t in threads]}


@router.get("/intake/search-terms")
def intake_search_terms(user: User = Depends(require_user)) -> dict:
    told, resume_text = _intake_corpus(paths_for(user))
    terms = extract_search_terms(told, resume_text, vocabulary=set(_vocabulary()))
    return {"keywords": list(terms.keywords), "guessed": terms.guessed}


# --- Chapter 5: live job inventory, no LLM ------------------------------------


def _preview_keywords(user: User) -> list[str]:
    """What "jobs that look like you" is allowed to mean.

    The user's own confirmed keywords when they have any; otherwise the terms
    derived from what they typed. Deliberately not the raw config value:
    ``UserPaths.ensure`` seeds every account from config.example.yaml, so a
    user who has not reached chapter 4 yet still "has" three keywords — written
    by us, about nobody. Counting postings against those and calling the result
    a match would be the one dishonest number in the whole journey.
    """
    cfg = load_config(user) or {}
    keywords = chosen_keywords(cfg)
    if keywords:
        return keywords
    told, resume_text = _intake_corpus(paths_for(user))
    return list(
        extract_search_terms(told, resume_text, vocabulary=set(_vocabulary())).keywords
    )


@router.post("/preview-jobs")
def start_preview_jobs(user: User = Depends(require_user)) -> dict:
    """Kick off the LLM-free scrape behind chapter 5.

    Fires while the user is still in chapter 4, so the count is usually ready by
    the time they arrive. Returns immediately either way; the client polls.
    """
    from . import job_preview

    cfg = load_config(user) or {}
    job_preview.start(user.id, cfg, _preview_keywords(user))
    return {"state": "running"}


@router.get("/preview-jobs")
def get_preview_jobs(user: User = Depends(require_user)) -> dict:
    from . import job_preview

    return job_preview.status(user.id)


# --- Chapter 6: the enrichment cascade ---------------------------------------

@router.get("/enrich/plan")
def enrich_plan(user: User = Depends(require_user)) -> dict:
    from . import enrichment

    return {"steps": enrichment.plan(user)}


class EnrichStepBody(BaseModel):
    step_id: str
    force: bool = False


@router.post("/enrich/step")
def enrich_step(body: EnrichStepBody, user: User = Depends(require_user)) -> dict:
    from . import enrichment

    return enrichment.run_step(user, body.step_id, force=body.force)
