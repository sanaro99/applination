"""Provider metadata and setup instructions, as data.

One source for the journey, the Config page and the CLI, replacing the one-line
hints that used to live in the frontend's PROVIDERS array.

**Gemini is the recommended default.** It has a genuine free tier with no card
required, and most people already have a Google account and no reason to
distrust it. DeepSeek stays available but is not offered first: it is the
cheapest paid path and a fine choice for someone who has decided to pay, but
offering it to a stranger asks for card details and prompts from a vendor many
will not recognise, at the moment they have least reason to trust us. Cheapness
is the wrong default when the user has no trust yet.

**Staleness is designed against, not hoped away.** The primary control is a deep
link to the key-creation page, not a click path; steps stay at three shallow
lines describing what the user will *see*, because shallow instructions survive
a vendor redesign. Nothing here quotes a number — quotas and prices rot, and
Gemini's free tier narrowed to Flash-only during this feature's design.
``verified_on`` is surfaced in the UI so the card can soften its own wording
once it is old.

The ``model`` values mirror config.example.yaml. Keep them in step: this file is
what the journey writes into a new account's config, so a drift here hands the
user a model name their config does not otherwise mention.
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends

from .auth import require_user
from .db import User

router = APIRouter(prefix="/api/providers", tags=["providers"])

STALE_AFTER = timedelta(days=90)

PROVIDERS: tuple[dict, ...] = (
    {
        "id": "gemini",
        "label": "Google Gemini",
        "recommended": True,
        "why": "Free tier, no card needed, and you probably already have a Google account.",
        "model": "gemini-2.5-flash",
        "console_url": "https://aistudio.google.com/apikey",
        "steps": [
            "Sign in with your Google account.",
            "Click Create API key.",
            "Copy it and paste it below.",
        ],
        "key_shape": {"prefix": "AIza", "min_len": 30},
        "cost_note": "Free tier covers the Flash models. Check Google's rate-limit page for current limits.",
        "needs_key": True,
        "verified_on": "2026-08-24",
    },
    {
        "id": "deepseek",
        "label": "DeepSeek",
        "recommended": False,
        "why": "The cheapest paid option, if you would rather pay than sit in a free tier.",
        "model": "deepseek-v4-flash",
        "console_url": "https://platform.deepseek.com/api_keys",
        "steps": [
            "Create an account and add credit.",
            "Open API keys and create one.",
            "Copy it and paste it below.",
        ],
        "key_shape": {"prefix": "sk-", "min_len": 20},
        "cost_note": "Paid only, billed per token. Cheapest of the cloud options here.",
        "needs_key": True,
        "verified_on": "2026-08-24",
    },
    {
        "id": "openrouter",
        "label": "OpenRouter",
        "recommended": False,
        "why": "One key for many models, including some free ones.",
        "model": "tencent/hy3-preview:free",
        "console_url": "https://openrouter.ai/keys",
        "steps": [
            "Sign in with Google or GitHub.",
            "Create a key.",
            "Copy it and paste it below.",
        ],
        "key_shape": {"prefix": "sk-or-", "min_len": 20},
        "cost_note": "Mixed: some models are free, most are paid per token.",
        "needs_key": True,
        "verified_on": "2026-08-24",
    },
    {
        "id": "mistral",
        "label": "Mistral",
        "recommended": False,
        "why": "European provider with a free experimentation tier.",
        "model": "mistral-small-latest",
        "console_url": "https://console.mistral.ai/api-keys",
        "steps": [
            "Create an account.",
            "Open API keys and create one.",
            "Copy it and paste it below.",
        ],
        "key_shape": {"prefix": "", "min_len": 20},
        "cost_note": "Free experimentation tier, paid beyond it.",
        "needs_key": True,
        "verified_on": "2026-08-24",
    },
    {
        "id": "claude",
        "label": "Anthropic Claude",
        "recommended": False,
        "why": "Strong writing quality, if you already have an Anthropic account.",
        "model": "claude-haiku-4-5-20251001",
        "console_url": "https://console.anthropic.com/settings/keys",
        "steps": [
            "Sign in and add credit.",
            "Open API keys and create one.",
            "Copy it and paste it below.",
        ],
        "key_shape": {"prefix": "sk-ant-", "min_len": 20},
        "cost_note": "Paid only, billed per token.",
        "needs_key": True,
        "verified_on": "2026-08-24",
    },
    {
        "id": "ollama",
        "label": "Ollama (local)",
        "recommended": False,
        "why": "Runs on your own machine. Nothing leaves it, and it costs nothing.",
        "model": "llama3.2",
        "console_url": "https://ollama.com/download",
        "steps": [
            "Install Ollama.",
            "Pull a model from a terminal.",
            "Leave the key blank and continue.",
        ],
        "key_shape": {"prefix": "", "min_len": 0},
        "cost_note": "Free. Quality depends on your hardware.",
        "needs_key": False,
        "verified_on": "2026-08-24",
    },
)


def stale(entry: dict, *, today: date | None = None) -> bool:
    """True once the setup steps are old enough to distrust.

    The UI softens its wording rather than hiding the card: the deep link stays
    authoritative even when the steps around it have drifted.
    """
    today = today or date.today()
    return date.fromisoformat(entry["verified_on"]) < today - STALE_AFTER


@router.get("/setup")
def setup(user: User = Depends(require_user)) -> dict:
    return {"providers": [{**p, "stale": stale(p)} for p in PROVIDERS]}
