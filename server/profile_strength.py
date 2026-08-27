"""How complete is this user's profile, and what is worth doing next.

Two phases. **Formation** is a finite set of nine parts that genuinely
completes at 100% — a progress indicator engineered never to fill is a dark
pattern, and this one fills. **Depth**, afterwards, drops the percentage
entirely and reports story coverage against the committed tag taxonomy.

Coverage is not gamification decoration: ``reference_loader.match_stories``
scores by tag overlap, so a gap here is a measurable weakness in the cover
letter the user is about to receive. The nudge is true, which is the only kind
worth shipping.

This module also owns the "is this part done?" predicates for the whole app —
``onboarding.py`` imports them rather than keeping a second copy that can drift.
"""
from __future__ import annotations

import os
from functools import lru_cache

import yaml
from fastapi import APIRouter, Depends

from src.intake_extract import load_vocabulary
from src.reference_loader import load_stories

from . import intake as intake_store
from .auth import require_user
from .db import User
from .deps import load_config, paths_for
from .user_paths import EXAMPLE_CONFIG_PATH, GLOBAL_MASTER_DIR, UserPaths
from .user_secrets import SECRET_PATHS, secret_names

router = APIRouter(prefix="/api/profile", tags=["profile"])

_PLACEHOLDER_NAMES = {"", "your name"}

# Provider -> env var that can supply its key (mirrors the providers layer).
_PROVIDER_ENV = {
    "claude": "ANTHROPIC_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "nim": "NVIDIA_API_KEY",
}

PARTS: tuple[tuple[str, str, str], ...] = (
    ("contact", "Contact details", "Your name and email, for the top of your documents."),
    ("material", "Something about you", "Tell me what you have been working on, or drop your resume."),
    ("resume", "Structured resume", "Connect a provider and I will turn your resume into structured data."),
    ("story_1", "First story", "Tell me about one thing you worked on."),
    ("story_2", "Second story", "A second story widens the roles you match."),
    ("story_3", "Third story", "Three stories is enough to cover most postings."),
    ("voice", "Your voice", "A short note on how you write, so letters sound like you."),
    ("search", "What to look for", "Confirm the roles I should be searching for."),
    ("provider", "AI provider", "Connect a provider so I can write, not just look."),
)


# --------------------------------------------------------------------------
# Template defaults are not user choices
#
# ``UserPaths.ensure`` seeds every new account from the committed
# config.example.yaml, so a brand-new config already carries example search
# keywords and an Ollama base_url. Reading either as evidence would hand a user
# two filled parts they never earned — and, worse, would have chapter 5 count
# "jobs that look like you" against keywords a stranger wrote.
# --------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _template_keywords() -> frozenset[str]:
    """The example keywords every fresh config.yaml is seeded with.

    Read from the committed template rather than hardcoded, so editing the
    example never silently starts counting its keywords as a user's own.
    """
    if not EXAMPLE_CONFIG_PATH.exists():
        return frozenset()
    try:
        data = yaml.safe_load(EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return frozenset()
    return frozenset(
        str(k).strip().lower() for k in ((data.get("search") or {}).get("keywords") or [])
    )


def chosen_keywords(cfg: dict) -> list[str]:
    """The search keywords this user actually chose, or ``[]``.

    A config whose keywords are still exactly the template's has not been
    through chapter 4 — the user has confirmed nothing, and treating the
    example as their answer would skip the one step that asks.
    """
    keywords = [
        str(k).strip()
        for k in ((cfg.get("search") or {}).get("keywords") or [])
        if str(k).strip()
    ]
    if not keywords:
        return []
    if {k.lower() for k in keywords} == _template_keywords():
        return []
    return keywords


def contact_ok(cfg: dict) -> bool:
    contact = cfg.get("user") or {}
    name = str(contact.get("full_name") or "").strip()
    email = str(contact.get("email") or "").strip()
    return (
        name.lower() not in _PLACEHOLDER_NAMES
        and bool(email)
        and "example.com" not in email
    )


def _ollama_chosen(llm: dict) -> bool:
    """True when Ollama is the provider this user actually picked.

    ``base_url`` alone proves nothing: the template ships localhost:11434 for
    everyone, installed or not. Selecting it — as primary or as a fallback — is
    the deliberate act, and it is what ``PUT /api/onboarding/provider`` records.
    """
    if not str((llm.get("ollama") or {}).get("base_url") or "").strip():
        return False
    if str(llm.get("primary") or "").strip().lower() == "ollama":
        return True
    return any(
        str(f).strip().lower() == "ollama" for f in (llm.get("fallbacks") or [])
    )


def provider_ready(llm: dict, user_id: int) -> bool:
    """True if at least one LLM provider can actually be called.

    ``load_config`` has already merged this user's stored keys into ``llm``, so
    a plain check of the config covers BYOK. The stored-name check behind it
    catches the case where the Fernet key is missing or rotated: the secret
    exists but could not be decrypted, and reporting "no provider" would send
    the user back to re-enter a key that is already there.

    The env-var fallback only counts when ALLOW_ENV_API_KEYS is on. Otherwise
    the providers layer refuses to use it, and reporting the user as ready would
    be a lie that surfaces as an auth error mid-run.
    """
    from src.providers import env_api_keys_allowed

    allow_env = env_api_keys_allowed()
    for name, env in _PROVIDER_ENV.items():
        block = llm.get(name) or {}
        if str(block.get("api_key") or "").strip():
            return True
        if allow_env and os.environ.get(env):
            return True
    if _ollama_chosen(llm):
        return True
    stored = set(secret_names(user_id))
    return any(p in stored for p in SECRET_PATHS if p.endswith(".api_key"))


def count_stories(paths: UserPaths) -> int:
    if not paths.stories_dir.exists():
        return 0
    return sum(1 for p in paths.stories_dir.glob("*.md") if not p.name.startswith("_"))


@lru_cache(maxsize=1)
def _vocabulary() -> frozenset[str]:
    index = GLOBAL_MASTER_DIR / "stories" / "_INDEX.md"
    if not index.exists():
        return frozenset()
    return frozenset(load_vocabulary(index.read_text(encoding="utf-8")))


def _coverage(paths: UserPaths) -> dict:
    """Which taxonomy tags the user's real stories carry, and which they do not.

    Gaps are alphabetical and capped: there is no signal available for ranking
    them, so the cap keeps the UI honest about showing a sample rather than
    implying these five are the most important five.

    ``total`` is the size of the whole taxonomy, and it is not recoverable from
    the other two — the cap means ``covered + gaps`` falls short of it. Without
    it the card can only report a bare count, and "two tags covered" says
    nothing about whether that is most of the taxonomy or a corner of it.
    """
    covered: set[str] = set()
    if paths.stories_dir.exists():
        for story in load_stories(paths.stories_dir):
            covered.update(str(t).lower() for t in (story.get("tags") or []))
    vocab = _vocabulary()
    gaps = sorted(vocab - covered)[:5]
    return {"covered": sorted(covered & vocab), "gaps": gaps, "total": len(vocab)}


def compute(user: User) -> dict:
    cfg = load_config(user) or {}
    paths = paths_for(user)
    llm = cfg.get("llm") or {}

    real_stories = count_stories(paths)
    drafts = len(intake_store.list_drafts(paths))
    parked = bool(intake_store.read_parked_resume(paths).strip())
    notes = bool(intake_store.read_notes(paths).strip())
    keywords = chosen_keywords(cfg)

    def story_state(index: int) -> str:
        if index <= real_stories:
            return "filled"
        if index <= real_stories + drafts:
            return "partial"
        return "empty"

    states = {
        "contact": "filled" if contact_ok(cfg) else "empty",
        "material": "filled" if (parked or notes or drafts or real_stories) else "empty",
        "resume": "filled" if paths.resume_path.exists() else ("partial" if parked else "empty"),
        "story_1": story_state(1),
        "story_2": story_state(2),
        "story_3": story_state(3),
        "voice": "filled" if paths.bio_path.exists() else ("partial" if notes else "empty"),
        "search": "filled" if keywords else "empty",
        "provider": "filled" if provider_ready(llm, user.id) else "empty",
    }

    parts = [
        {"id": rid, "label": label, "hint": hint, "state": states[rid]}
        for rid, label, hint in PARTS
    ]
    filled = sum(1 for r in parts if r["state"] == "filled")
    partial = sum(1 for r in parts if r["state"] == "partial")
    total = len(parts)
    nxt = next((r for r in parts if r["state"] != "filled"), None)

    return {
        "phase": "depth" if filled == total else "formation",
        "filled": filled,
        "partial": partial,
        "total": total,
        "score": (filled + 0.5 * partial) / total,
        "parts": parts,
        "next": (
            {"id": nxt["id"], "label": nxt["label"], "hint": nxt["hint"]}
            if nxt
            else None
        ),
        "coverage": _coverage(paths),
    }


@router.get("/strength")
def strength(user: User = Depends(require_user)) -> dict:
    return compute(user)
