"""Provider metadata and setup instructions, as data.

One source for the journey, the Config page and the CLI, replacing the one-line
hints that used to live in the frontend's PROVIDERS array.

**DeepSeek is the recommended starting point.** The routing preset uses
DeepSeek V4.1 Flash for every workflow, then falls back through Groq, Gemini,
and Cloudflare. Other paid providers stay available but are never added to that
automatic chain.

**Staleness is designed against, not hoped away.** The primary control is a deep
link to the key-creation page, not a click path; steps stay at a handful of
lines naming what the user will *see* (the button label, the page name), because
shallow instructions survive a vendor redesign better than a menu path does.
Each entry also carries a sign-up link, a billing link where the provider is
prepaid, the official docs, and a plain description of what a valid key looks
like, so the guide can answer "did I copy the right thing?". Nothing here quotes a number — quotas and prices rot, and
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
        "recommended": False,
        "why": "Free tier, no card needed, and you probably already have a Google account.",
        "model": "gemini-3.8-flash",
        "console_url": "https://aistudio.google.com/apikey",
        "signup_url": "https://aistudio.google.com/",
        "billing_url": None,
        "docs_url": "https://ai.google.dev/gemini-api/docs/api-key",
        "steps": [
            "Open Google AI Studio and sign in with your Google account.",
            "Accept the terms on your first visit. AI Studio may create a default project and key for you.",
            "On the API keys page, click Create API key and pick a project (or let it make one).",
            "Copy the key and paste it below.",
        ],
        # Since mid-2026 AI Studio issues service-account "auth keys"; their
        # format is not documented, so no prefix is enforced.
        "key_shape": {"prefix": "", "min_len": 30},
        "key_hint": "A long string of letters, digits, dashes and underscores (older keys start with AIza).",
        "shown_once": False,
        "cost_note": "The free tier needs no card and covers the Flash models. Turn on billing for the project in AI Studio only if you hit the free limits.",
        "needs_key": True,
        "verified_on": "2026-11-20",
    },
    {
        "id": "openai",
        "label": "OpenAI",
        "recommended": False,
        "why": "GPT Luna is a capable, cost-conscious option for high-volume application work.",
        "model": "gpt-5.6-luna",
        "console_url": "https://platform.openai.com/api-keys",
        "signup_url": "https://platform.openai.com/signup",
        "billing_url": "https://platform.openai.com/settings/organization/billing/overview",
        "docs_url": "https://developers.openai.com/api/docs/quickstart",
        "steps": [
            "Sign in to the OpenAI platform. This is a separate account from a ChatGPT subscription.",
            "Open Billing and add prepaid credit. Without credit, requests fail with a quota error.",
            "Open API keys, click Create new secret key, and give it a name.",
            "Copy the key right away and paste it below.",
        ],
        "key_shape": {"prefix": "sk-", "min_len": 20},
        "key_hint": "Starts with sk- (new project keys start with sk-proj-).",
        "shown_once": True,
        "cost_note": "Prepaid and billed per token. Some newer models also ask you to verify your organization first.",
        "needs_key": True,
        "verified_on": "2026-11-20",
    },
    {
        "id": "deepseek",
        "label": "DeepSeek",
        "recommended": True,
        "why": "Strong long-context reasoning and writing at the lowest paid cost here.",
        "model": "deepseek-flash",
        "console_url": "https://platform.deepseek.com/api_keys",
        "signup_url": "https://platform.deepseek.com/",
        "billing_url": "https://platform.deepseek.com/top_up",
        "docs_url": "https://api-docs.deepseek.com/",
        "steps": [
            "Create an account on the DeepSeek platform (not the chat app).",
            "Open Top up and add balance. Requests fail with an insufficient balance error until you do.",
            "Open API keys, click Create new API key, and name it.",
            "Copy the key right away and paste it below.",
        ],
        "key_shape": {"prefix": "sk-", "min_len": 20},
        "key_hint": "Starts with sk- followed by letters and digits.",
        "shown_once": True,
        "cost_note": "Prepaid only, billed per token. Cheapest of the cloud options here.",
        "needs_key": True,
        "verified_on": "2026-11-20",
    },
    {
        "id": "openrouter",
        "label": "OpenRouter",
        "recommended": False,
        "why": "One key for many models, including some free ones.",
        "model": "nex-agi/nex-n2.5-mini:free",
        "console_url": "https://openrouter.ai/keys",
        "signup_url": "https://openrouter.ai/",
        "billing_url": "https://openrouter.ai/settings/credits",
        "docs_url": "https://openrouter.ai/docs/quickstart",
        "steps": [
            "Sign in with Google or GitHub, or with an email address.",
            "Open Keys and click Create. You can set a credit limit for the key.",
            "Copy the key right away and paste it below.",
            "To use paid models, or for a higher daily cap on free ones, add credits.",
        ],
        "key_shape": {"prefix": "sk-or-", "min_len": 20},
        "key_hint": "Starts with sk-or- (usually sk-or-v1-).",
        "shown_once": True,
        "cost_note": "Models ending in :free cost nothing but have a daily request cap. Others are paid per token from your credits.",
        "needs_key": True,
        "verified_on": "2026-11-20",
    },
    {
        "id": "mistral",
        "label": "Mistral",
        "recommended": False,
        "why": "European provider with a free experimentation tier.",
        "model": "mistral-small-latest",
        "console_url": "https://console.mistral.ai/api-keys",
        "signup_url": "https://console.mistral.ai/",
        "billing_url": None,
        "docs_url": "https://docs.mistral.ai/getting-started/quickstarts/studio/activate-and-generate-api-key",
        "steps": [
            "Create an account in Mistral AI Studio.",
            "Choose a plan: Experiment is free and needs a verified phone number, Scale is pay as you go.",
            "Open API Keys, click New key, and give it a name and expiry.",
            "Copy the key before closing the dialog and paste it below.",
        ],
        "key_shape": {"prefix": "", "min_len": 20},
        "key_hint": "A string of letters and digits with no fixed prefix.",
        "shown_once": True,
        "cost_note": "The free Experiment plan may use your requests to train Mistral's models. The paid Scale plan does not.",
        "needs_key": True,
        "verified_on": "2026-11-20",
    },
    {
        "id": "claude",
        "label": "Anthropic Claude",
        "recommended": False,
        "why": "Strong writing quality, if you already have an Anthropic account.",
        "model": "claude-haiku-4-5-20251001",
        "console_url": "https://platform.claude.com/settings/keys",
        "signup_url": "https://platform.claude.com/",
        "billing_url": "https://platform.claude.com/settings/billing",
        "docs_url": "https://platform.claude.com/docs/en/get-api-key",
        "steps": [
            "Sign in to the Claude Console, or create an account. A Claude.ai chat plan does not include API use.",
            "Open Billing and buy credits.",
            "Open API keys, click Create key, and give it a name.",
            "Copy the key right away and paste it below.",
        ],
        "key_shape": {"prefix": "sk-ant-", "min_len": 20},
        "key_hint": "Starts with sk-ant- (usually sk-ant-api03-).",
        "shown_once": True,
        "cost_note": "Prepaid only, billed per token.",
        "needs_key": True,
        "verified_on": "2026-11-20",
    },
    {
        "id": "nim",
        "label": "NVIDIA NIM",
        "recommended": False,
        "why": "Strong long-context writing through NVIDIA's current free prototype endpoint.",
        "model": "nvidia/nemotron-3-super-120b-a12b",
        "console_url": "https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b/build",
        "signup_url": "https://build.nvidia.com/",
        "billing_url": None,
        "docs_url": "https://docs.api.nvidia.com/",
        "steps": [
            "Sign in to NVIDIA Build with email, Google or GitHub, and verify your email.",
            "On the model page, click Get API Key, then Generate Key.",
            "Copy the key right away and paste it below.",
            "If key creation is blocked, your account needs verification. Ask on NVIDIA's developer forum.",
        ],
        "key_shape": {"prefix": "nvapi-", "min_len": 20},
        "key_hint": "Starts with nvapi-.",
        "shown_once": True,
        "cost_note": "Free prototype endpoint with tight per-minute limits; treat its quota and availability as a trial.",
        "needs_key": True,
        "verified_on": "2026-11-20",
    },
    {
        "id": "groq",
        "label": "Groq",
        "recommended": False,
        "why": "Very fast flagship GPT-OSS for compact ranking and structured tasks.",
        "model": "openai/gpt-oss-120b",
        "console_url": "https://console.groq.com/keys",
        "signup_url": "https://console.groq.com/",
        "billing_url": "https://console.groq.com/settings/billing",
        "docs_url": "https://console.groq.com/docs/quickstart",
        "steps": [
            "Sign in to GroqCloud with email, Google or GitHub.",
            "Open API Keys and click Create API Key.",
            "Copy the key right away and paste it below.",
        ],
        "key_shape": {"prefix": "gsk_", "min_len": 20},
        "key_hint": "Starts with gsk_.",
        "shown_once": True,
        "cost_note": "The free plan needs no card. Its limits suit short, structured requests rather than full resume generation.",
        "needs_key": True,
        "verified_on": "2026-11-20",
    },
    {
        "id": "cloudflare",
        "label": "Cloudflare Workers AI",
        "recommended": False,
        "why": "Private fallback pool with a daily free Workers AI allocation.",
        "model": "@cf/google/gemma-4-26b-a4b-it",
        "console_url": "https://dash.cloudflare.com/?to=/:account/ai/workers-ai",
        "signup_url": "https://dash.cloudflare.com/sign-up/workers-and-pages",
        "billing_url": None,
        "docs_url": "https://developers.cloudflare.com/workers-ai/get-started/rest-api/",
        "steps": [
            "Sign in to the Cloudflare dashboard and open AI, then Workers AI.",
            "Select Use REST API.",
            "Click Create a Workers AI API Token, review it, click Create API Token, then copy it.",
            "Copy the Account ID shown on the same page. Applination needs both the token and the Account ID.",
        ],
        "key_shape": {"prefix": "", "min_len": 20},
        "key_hint": "The API token is a long string of letters, digits, dashes and underscores. The Account ID is a separate string of letters and digits.",
        "shown_once": True,
        "cost_note": "Free allocation resets daily; Workers AI does not train on content without explicit consent. A custom token needs Workers AI Read and Edit.",
        "needs_key": True,
        "verified_on": "2026-11-20",
    },
    {
        "id": "ollama",
        "label": "Ollama (local)",
        "recommended": False,
        "why": "Runs AI requests on your computer, so AI companies cannot use data processed by your local model.",
        "model": "llama3.2",
        "console_url": "https://ollama.com/download",
        "signup_url": None,
        "billing_url": None,
        "docs_url": "https://docs.ollama.com/",
        "steps": [
            "Install Ollama.",
            "Pull the suggested model from a terminal.",
            "Connect the Applination Ollama worker below. No AI provider key is needed.",
        ],
        "key_shape": {"prefix": "", "min_len": 0},
        "key_hint": "",
        "shown_once": False,
        "cost_note": "No AI provider charge. Speed and quality depend on your computer and model.",
        "needs_key": False,
        "verified_on": "2026-09-27",
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
