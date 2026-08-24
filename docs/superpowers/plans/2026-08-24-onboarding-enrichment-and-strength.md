# Onboarding Enrichment & Profile Strength — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the raw material captured by plan 1 into a real profile — a strength model the dashboard can show forever, provider setup instructions that do not rot, the zero-token live-job payoff, and the per-step enrichment cascade that runs once a key exists.

**Architecture:** `server/profile_strength.py` becomes the single home for "is this part of the profile done?", which `onboarding.py` then imports instead of duplicating. `server/provider_setup.py` holds provider metadata as data, with a freshness date and a link checker. `POST /api/onboarding/preview-jobs` runs the LLM-free `fetch_all()` on a daemon thread, cached per user. `enrich/plan` + `enrich/step` drive the cascade one idempotent step at a time, client-driven so ridge animation reflects real progress.

**Tech Stack:** Python 3, FastAPI, SQLModel, pytest, `fastapi.testclient.TestClient`, `threading`.

**Spec:** `docs/superpowers/specs/2026-08-24-onboarding-journey-design.md`

**Predecessor:** `docs/superpowers/plans/2026-08-24-onboarding-capture-backbone.md` (complete — `server/intake.py`, `src/intake_extract.py`, the `_intake` tree, and five intake endpoints all exist and are tested).

## Plan set

Plan **2 of 3**. Plan 1 is done. Plan 3 is the journey UI and depends on this one.

## Global Constraints

- **Everything except Task 5 must work with no API key configured.** Only `enrich/step` may call a provider, and only because it runs *after* the user connects one.
- **Never join a path onto `data/users` by hand.** `server/user_paths.resolve_within` is the single door.
- **Every DB query against a tenant table** goes through `server/scoping.py` or carries an explicit `# noscope: <reason>`. `tests/test_scope_lint.py` fails the build otherwise.
- **Enrichment steps are idempotent** — skipped when their output already exists unless `force=true` — and **drafts are moved to `_intake/consumed/`, never deleted.**
- **`search` enrichment proposes, never writes.** It returns keywords; the user's chips are theirs.
- **Never print a numeric quota or price** in provider setup copy. Gemini's free tier narrowed to Flash-only during the design of this feature; any number we ship goes stale.
- Tests: run with `.venv/Scripts/python.exe -m pytest` on Windows. Baseline after plan 1 is **352 passing**.
- Providers are faked in tests by monkeypatching `src.providers.get_provider_chain` / `get_provider` / `get_task_chains` — see `tests/test_studio.py:23-66` for the established pattern.

---

## File Structure

| File | Responsibility |
|---|---|
| `server/profile_strength.py` *(create)* | The profile completeness model + its router. Owns the "is this done?" predicates for the whole app. |
| `server/onboarding.py` *(modify)* | Import the predicates instead of duplicating them; add preview-jobs and enrich routes. |
| `server/provider_setup.py` *(create)* | Provider metadata as data, with `verified_on`. |
| `server/job_preview.py` *(create)* | Background `fetch_all()` runner + per-user cache. |
| `server/enrichment.py` *(create)* | Step enumeration and execution. The only module here that calls an LLM. |
| `server/app.py` *(modify)* | Register the two new routers inside `protected`. |
| `scripts/check_provider_links.py` *(create)* | Manual/scheduled link rot check. Deliberately not a test. |
| `tests/test_profile_strength.py` *(create)* | Ridge states, phases, coverage. |
| `tests/test_provider_setup.py` *(create)* | Metadata shape, no numbers in copy, freshness. |
| `tests/test_job_preview.py` *(create)* | Caching, partial-source degradation, never blocking. |
| `tests/test_enrichment.py` *(create)* | Plan enumeration, idempotency, drafts consumed not deleted. |

---

### Task 1: The profile strength model

**Files:**
- Create: `server/profile_strength.py`
- Modify: `server/onboarding.py` (replace `_provider_ready`, `_count_stories`, and the inline contact check with imports)
- Modify: `server/app.py:170-186` (add the router to `protected`)
- Test: `tests/test_profile_strength.py`

**Interfaces:**
- Consumes: `server.intake.list_drafts`, `read_parked_resume`; `src.intake_extract.load_vocabulary`; `src.reference_loader.load_stories`.
- Produces:
  - `contact_ok(cfg: dict) -> bool`
  - `provider_ready(llm: dict, user_id: int) -> bool`
  - `count_stories(paths: UserPaths) -> int`
  - `compute(user: User) -> dict` — `{"phase", "filled", "total", "score", "ridges", "next", "coverage"}`
  - `router` — `APIRouter(prefix="/api/profile", tags=["profile"])` exposing `GET /api/profile/strength`

Ridge ids and order are fixed: `contact`, `material`, `resume`, `story_1`, `story_2`, `story_3`, `voice`, `search`, `provider`. Each ridge has `state` in `{"empty", "partial", "filled"}`; `partial` exists so that a draft story renders as a half-filled ridge and *visibly completes* during the plan-2 cascade.

- [ ] **Step 1: Write the failing test**

Create `tests/test_profile_strength.py`:

```python
"""The fingerprint's data model.

Two phases, both honest: formation genuinely completes at 100%, and only then
does the card switch to story coverage. A bar engineered never to fill is a
dark pattern, so nothing here may produce one.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server.db as db
from server.intake import save_draft_story
from server.profile_strength import compute
from server.user_paths import UserPaths

from .conftest import make_engine, register


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, "engine", engine)
    from server.app import app

    return app


@pytest.fixture()
def client(app_env):
    with TestClient(app_env) as c:
        register(c, "a@example.com")
        yield c


def _user(uid: int = 1):
    from server.db import User, session

    with session() as s:
        return s.get(User, uid)  # noscope: test helper, explicit id


def test_a_fresh_account_has_nine_empty_ridges(client):
    out = compute(_user())
    assert out["total"] == 9
    assert out["filled"] == 0
    assert out["phase"] == "formation"
    assert [r["id"] for r in out["ridges"]] == [
        "contact", "material", "resume", "story_1", "story_2",
        "story_3", "voice", "search", "provider",
    ]


def test_a_draft_story_is_a_partial_ridge_not_a_filled_one(client):
    save_draft_story(UserPaths(user_id=1).ensure(), "A story", "body text")
    out = compute(_user())
    states = {r["id"]: r["state"] for r in out["ridges"]}
    assert states["story_1"] == "partial"
    assert states["material"] == "filled"
    assert 0 < out["score"] < 1


def test_a_real_story_fills_the_ridge(client):
    paths = UserPaths(user_id=1).ensure()
    (paths.stories_dir / "real.md").write_text(
        '---\ntitle: "Real"\ntags: [backend, python]\n---\n\nBody.\n', encoding="utf-8"
    )
    out = compute(_user())
    states = {r["id"]: r["state"] for r in out["ridges"]}
    assert states["story_1"] == "filled"


def test_next_names_the_first_unfinished_ridge(client):
    out = compute(_user())
    assert out["next"]["id"] == "contact"
    assert out["next"]["hint"]


def test_score_is_zero_to_one(client):
    out = compute(_user())
    assert 0.0 <= out["score"] <= 1.0


def test_coverage_reports_tags_the_stories_actually_carry(client):
    paths = UserPaths(user_id=1).ensure()
    (paths.stories_dir / "real.md").write_text(
        '---\ntitle: "Real"\ntags: [backend, python]\n---\n\nBody.\n', encoding="utf-8"
    )
    out = compute(_user())
    assert "backend" in out["coverage"]["covered"]
    assert "python" in out["coverage"]["covered"]
    assert "backend" not in out["coverage"]["gaps"]


def test_coverage_on_an_empty_account_is_empty_not_an_error(client):
    out = compute(_user())
    assert out["coverage"]["covered"] == []


def test_endpoint_returns_the_model(client):
    r = client.get("/api/profile/strength")
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 9


def test_endpoint_requires_a_session(app_env):
    with TestClient(app_env) as anon:
        assert anon.get("/api/profile/strength").status_code == 401


def test_onboarding_status_still_works_after_the_refactor(client):
    r = client.get("/api/onboarding/status")
    assert r.status_code == 200, r.text
    assert "steps" in r.json() and "intake" in r.json()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_strength.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.profile_strength'`

- [ ] **Step 3: Write minimal implementation**

Create `server/profile_strength.py`:

```python
"""How complete is this user's profile, and what is worth doing next.

Two phases. **Formation** is a finite set of nine ridges that genuinely
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

from fastapi import APIRouter, Depends

from src.intake_extract import load_vocabulary
from src.reference_loader import load_stories

from . import intake as intake_store
from .auth import require_user
from .db import User
from .deps import load_config, paths_for
from .user_paths import GLOBAL_MASTER_DIR, UserPaths
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

RIDGES: tuple[tuple[str, str, str], ...] = (
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


def contact_ok(cfg: dict) -> bool:
    contact = cfg.get("user") or {}
    name = str(contact.get("full_name") or "").strip()
    email = str(contact.get("email") or "").strip()
    return (
        name.lower() not in _PLACEHOLDER_NAMES
        and bool(email)
        and "example.com" not in email
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
    ollama = llm.get("ollama") or {}
    if str(ollama.get("base_url") or "").strip():
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
    """
    covered: set[str] = set()
    if paths.stories_dir.exists():
        for story in load_stories(paths.stories_dir):
            covered.update(str(t).lower() for t in (story.get("tags") or []))
    vocab = _vocabulary()
    gaps = sorted(vocab - covered)[:5]
    return {"covered": sorted(covered & vocab), "gaps": gaps}


def compute(user: User) -> dict:
    cfg = load_config(user) or {}
    paths = paths_for(user)
    llm = cfg.get("llm") or {}

    real_stories = count_stories(paths)
    drafts = len(intake_store.list_drafts(paths))
    parked = bool(intake_store.read_parked_resume(paths).strip())
    notes = bool(intake_store.read_notes(paths).strip())
    keywords = (cfg.get("search") or {}).get("keywords") or []

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

    ridges = [
        {"id": rid, "label": label, "hint": hint, "state": states[rid]}
        for rid, label, hint in RIDGES
    ]
    filled = sum(1 for r in ridges if r["state"] == "filled")
    partial = sum(1 for r in ridges if r["state"] == "partial")
    total = len(ridges)
    nxt = next((r for r in ridges if r["state"] != "filled"), None)

    return {
        "phase": "depth" if filled == total else "formation",
        "filled": filled,
        "partial": partial,
        "total": total,
        "score": (filled + 0.5 * partial) / total,
        "ridges": ridges,
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
```

- [ ] **Step 4: Wire the router**

In `server/app.py`, add the import beside the other router imports (mirroring how `onboarding_router` is imported), and add `profile_router` to the `protected` tuple at `server/app.py:170-186`:

```python
        onboarding_router,
        profile_router,
        files_router,
```

- [ ] **Step 5: Remove the duplicated predicates from `onboarding.py`**

In `server/onboarding.py`, delete `_PROVIDER_ENV`, `_PLACEHOLDER_NAMES`, `_provider_ready` and `_count_stories`, and import the replacements:

```python
from .profile_strength import contact_ok, count_stories, provider_ready
```

Then in `_compute_status`, replace the three inline checks:

```python
    contact_ok_ = contact_ok(cfg)
    provider_ok = provider_ready(llm, user_id)
    resume_ok = paths.resume_path.exists()
    bio_ok = paths.bio_path.exists()
    stories = count_stories(paths)
```

and use `contact_ok_` where `contact_ok` was previously the local variable. Leave the returned dict shape exactly as it is — `test_onboarding_status_still_works_after_the_refactor` and the whole of `tests/test_intake_api.py` depend on it.

Remove the now-unused `os` and `secret_names`/`SECRET_PATHS` imports **only if** nothing else in the file still uses them; check before deleting.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_strength.py tests/test_intake_api.py -q`
Expected: 20 passed

- [ ] **Step 7: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: all pass (≥362). The refactor touches a predicate several suites rely on, so a regression here is the expected failure mode — investigate rather than adjusting the tests.

- [ ] **Step 8: Commit**

```bash
git add server/profile_strength.py server/onboarding.py server/app.py tests/test_profile_strength.py
git commit -m "feat: profile strength model behind the fingerprint"
```

---

### Task 2: Provider setup metadata

**Files:**
- Create: `server/provider_setup.py`
- Create: `scripts/check_provider_links.py`
- Modify: `server/app.py` (register the router — it is added to `provider_setup.router`, mounted under `protected`)
- Test: `tests/test_provider_setup.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `PROVIDERS: tuple[dict, ...]` — each with `id`, `label`, `recommended`, `why`, `model`, `console_url`, `steps` (≤3 strings), `key_shape` (`{"prefix": str, "min_len": int}`), `cost_note`, `needs_key`, `verified_on`.
  - `router` — `APIRouter(prefix="/api/providers", tags=["providers"])` exposing `GET /api/providers/setup`.
  - `stale(entry: dict, *, today: date | None = None) -> bool` — True past 90 days.

- [ ] **Step 1: Write the failing test**

Create `tests/test_provider_setup.py`:

```python
"""Provider setup metadata.

Staleness is the risk this file exists to manage: instructions rot, vendors
redesign consoles, and free tiers narrow. The tests enforce the two rules that
keep the copy durable — deep links instead of click paths, and never a number.
"""
from __future__ import annotations

import re
from datetime import date

import pytest
from fastapi.testclient import TestClient

import server.db as db
from server.provider_setup import PROVIDERS, stale

from .conftest import make_engine, register


@pytest.fixture()
def client(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, "engine", engine)
    from server.app import app

    with TestClient(app) as c:
        register(c, "a@example.com")
        yield c


def test_exactly_one_provider_is_recommended():
    assert sum(1 for p in PROVIDERS if p["recommended"]) == 1


def test_gemini_is_the_recommended_one():
    recommended = next(p for p in PROVIDERS if p["recommended"])
    assert recommended["id"] == "gemini"


def test_gemini_is_listed_first():
    assert PROVIDERS[0]["id"] == "gemini"


def test_every_provider_has_the_required_fields():
    required = {
        "id", "label", "recommended", "why", "model", "console_url",
        "steps", "key_shape", "cost_note", "needs_key", "verified_on",
    }
    for p in PROVIDERS:
        assert required <= set(p), f"{p['id']} is missing {required - set(p)}"


def test_steps_stay_shallow():
    """Three lines survives a vendor redesign; a nine-step click path does not."""
    for p in PROVIDERS:
        assert 0 < len(p["steps"]) <= 3, p["id"]


def test_no_copy_quotes_a_number():
    """Quotas and prices go stale. Gemini's free tier narrowed to Flash-only
    while this feature was being designed."""
    digits = re.compile(r"\d")
    for p in PROVIDERS:
        assert not digits.search(p["cost_note"]), p["id"]
        assert not digits.search(p["why"]), p["id"]
        for step in p["steps"]:
            assert not digits.search(step), p["id"]


def test_console_urls_are_https_deep_links():
    for p in PROVIDERS:
        if not p["needs_key"]:
            continue
        assert p["console_url"].startswith("https://"), p["id"]


def test_verified_on_parses_as_a_date():
    for p in PROVIDERS:
        date.fromisoformat(p["verified_on"])


def test_stale_flags_old_entries():
    assert stale({"verified_on": "2020-01-01"}, today=date(2026, 8, 24)) is True
    assert stale({"verified_on": "2026-08-01"}, today=date(2026, 8, 24)) is False


def test_endpoint_returns_providers_with_a_stale_flag(client):
    r = client.get("/api/providers/setup")
    assert r.status_code == 200, r.text
    body = r.json()["providers"]
    assert body[0]["id"] == "gemini"
    assert "stale" in body[0]


def test_endpoint_requires_a_session(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, "engine", engine)
    from server.app import app

    with TestClient(app) as anon:
        assert anon.get("/api/providers/setup").status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_provider_setup.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.provider_setup'`

- [ ] **Step 3: Write minimal implementation**

Create `server/provider_setup.py`:

```python
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
```

- [ ] **Step 4: Wire the router**

Add `provider_setup.router` to the `protected` tuple in `server/app.py:170-186`, mirroring Task 1.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_provider_setup.py -q`
Expected: 12 passed

- [ ] **Step 6: Write the link checker**

Create `scripts/check_provider_links.py`:

```python
"""Check that provider console links still resolve.

Deliberately NOT a unit test: it makes real network calls, and network flake
must never break the build. Run it manually or on a schedule. A clean run is
what licenses bumping ``verified_on`` in server/provider_setup.py.

    python scripts/check_provider_links.py
"""
from __future__ import annotations

import sys

import httpx

from server.provider_setup import PROVIDERS


def main() -> int:
    failures = 0
    with httpx.Client(follow_redirects=True, timeout=20.0) as client:
        for entry in PROVIDERS:
            url = entry["console_url"]
            try:
                resp = client.get(url)
            except Exception as exc:  # noqa: BLE001
                print(f"FAIL {entry['id']:12} {url} -> {exc}")
                failures += 1
                continue
            landed = str(resp.url)
            status = "OK  " if resp.status_code < 400 else "FAIL"
            if resp.status_code >= 400:
                failures += 1
            note = "" if landed == url else f"  (redirected to {landed})"
            print(f"{status} {entry['id']:12} {resp.status_code} {url}{note}")
    print()
    if failures:
        print(f"{failures} link(s) need attention. Do not bump verified_on.")
    else:
        print("All links resolved. Re-read the pages before bumping verified_on:")
        print("a 200 proves the URL lives, not that the steps still match.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 7: Run the link checker once**

Run: `.venv/Scripts/python.exe scripts/check_provider_links.py`
Expected: every line `OK`. A redirect note is informational, not a failure — but if a link lands on a marketing homepage rather than a key page, fix the URL now.

- [ ] **Step 8: Commit**

```bash
git add server/provider_setup.py scripts/check_provider_links.py server/app.py tests/test_provider_setup.py
git commit -m "feat: provider setup metadata with a freshness date and link checker"
```

---

### Task 3: The live-job payoff

**Files:**
- Create: `server/job_preview.py`
- Modify: `server/onboarding.py` (two routes)
- Test: `tests/test_job_preview.py`

**Interfaces:**
- Consumes: `src.main.fetch_all`, `server.deps.load_config`, `src.intake_extract.extract_search_terms`.
- Produces:
  - `start(user_id: int, cfg: dict, keywords: list[str]) -> None` — spawns the daemon thread if one is not already running.
  - `status(user_id: int) -> dict` — `{"state", "total", "matched", "sources_ok", "sources_total", "sample", "error"}` with `state` in `{"idle", "running", "ready", "error"}`.
  - `POST /api/onboarding/preview-jobs` → `{"state": "running"}`
  - `GET /api/onboarding/preview-jobs` → the status dict

`matched` is a **deterministic keyword-overlap count**, not an LLM ranking — chapter 5 costs zero tokens. The copy in plan 3 says "look like you", which this honestly supports: it means the posting's title or description mentions something the user said.

- [ ] **Step 1: Write the failing test**

Create `tests/test_job_preview.py`:

```python
"""Chapter 5's payoff: real job inventory, zero tokens.

fetch_all() is pure HTTP, so this whole feature works before the user has an
API key. The tests fake it — the point is the caching, the degradation and the
counting, not the network.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server.db as db
import server.job_preview as job_preview

from .conftest import make_engine, register


class _Job:
    def __init__(self, title, company="Acme", description=""):
        self.title = title
        self.company = company
        self.description = description
        self.url = "https://example.com/j"
        self.location = "Remote"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, "engine", engine)
    job_preview.reset()
    from server.app import app

    with TestClient(app) as c:
        register(c, "a@example.com")
        yield c


def test_status_before_anything_started_is_idle(client):
    r = client.get("/api/onboarding/preview-jobs")
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "idle"


def test_a_preview_runs_and_counts_matches(client, monkeypatch):
    monkeypatch.setattr(
        job_preview,
        "_fetch",
        lambda cfg: (
            [_Job("Backend Engineer"), _Job("Chef"), _Job("Python Developer")],
            9,
            9,
        ),
    )
    client.post(
        "/api/onboarding/intake/notes",
        json={"text": "I'm a backend engineer who writes python"},
    )
    assert client.post("/api/onboarding/preview-jobs").status_code == 200
    body = client.get("/api/onboarding/preview-jobs").json()
    assert body["state"] == "ready"
    assert body["total"] == 3
    assert body["matched"] == 2
    assert len(body["sample"]) == 2


def test_partial_source_failure_is_reported_not_fatal(client, monkeypatch):
    monkeypatch.setattr(
        job_preview, "_fetch", lambda cfg: ([_Job("Backend Engineer")], 6, 9)
    )
    client.post("/api/onboarding/preview-jobs")
    body = client.get("/api/onboarding/preview-jobs").json()
    assert body["state"] == "ready"
    assert body["sources_ok"] == 6
    assert body["sources_total"] == 9


def test_a_failing_fetch_becomes_an_error_state_not_a_500(client, monkeypatch):
    def boom(cfg):
        raise RuntimeError("network down")

    monkeypatch.setattr(job_preview, "_fetch", boom)
    client.post("/api/onboarding/preview-jobs")
    body = client.get("/api/onboarding/preview-jobs").json()
    assert body["state"] == "error"
    assert "network down" in body["error"]


def test_results_are_cached_per_user(client, monkeypatch):
    calls = []

    def counting(cfg):
        calls.append(1)
        return ([_Job("Backend Engineer")], 9, 9)

    monkeypatch.setattr(job_preview, "_fetch", counting)
    client.post("/api/onboarding/preview-jobs")
    client.post("/api/onboarding/preview-jobs")
    assert len(calls) == 1


def test_preview_requires_a_session(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, "engine", engine)
    from server.app import app

    with TestClient(app) as anon:
        assert anon.get("/api/onboarding/preview-jobs").status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_job_preview.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.job_preview'`

- [ ] **Step 3: Write minimal implementation**

Create `server/job_preview.py`:

```python
"""Chapter 5: how many real jobs are out there for this person, right now.

``src.main.fetch_all`` is pure HTTP — no LLM anywhere — so this runs before the
user has a key, which is what makes the payoff possible at that point in the
journey. It is also slow (nine external services), so it runs on a daemon
thread and the client polls.

``matched`` is deterministic keyword overlap, not a ranking. Chapter 5 says
these postings "look like you", and what that honestly means is: the title or
description mentions something the user just told us.
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("server.job_preview")

CACHE_TTL_SECONDS = 30 * 60
SAMPLE_SIZE = 12

_lock = threading.Lock()
_state: dict[int, dict] = {}


def reset() -> None:
    """Drop all cached previews. For tests."""
    with _lock:
        _state.clear()


def _fetch(cfg: dict) -> tuple[list, int, int]:
    """Run the real scrapers. Returns (jobs, sources_ok, sources_total).

    Split out as a module-level function so tests can replace it without
    touching the threading or caching around it.
    """
    from src.main import fetch_all

    sources = cfg.get("sources") or {}
    total = sum(1 for v in sources.values() if isinstance(v, dict) and v.get("enabled"))
    jobs = fetch_all(cfg, log)
    # fetch_all swallows individual source failures, so a short result is the
    # only signal available. Report the enabled count as both until the scraper
    # layer reports per-source outcomes.
    return jobs, total, total


def _matches(job, keywords: list[str]) -> bool:
    haystack = f"{getattr(job, 'title', '')} {getattr(job, 'description', '')}".lower()
    return any(k.lower() in haystack for k in keywords)


def _worker(user_id: int, cfg: dict, keywords: list[str]) -> None:
    try:
        jobs, ok, total = _fetch(cfg)
    except Exception as exc:  # noqa: BLE001
        log.warning("job preview failed for user %s: %s", user_id, exc)
        with _lock:
            _state[user_id] = {
                "state": "error",
                "error": str(exc),
                "fetched_at": time.time(),
            }
        return

    matched = [j for j in jobs if _matches(j, keywords)] if keywords else []
    with _lock:
        _state[user_id] = {
            "state": "ready",
            "total": len(jobs),
            "matched": len(matched),
            "sources_ok": ok,
            "sources_total": total,
            "sample": [
                {
                    "title": getattr(j, "title", ""),
                    "company": getattr(j, "company", ""),
                    "location": getattr(j, "location", ""),
                    "url": getattr(j, "url", ""),
                }
                for j in matched[:SAMPLE_SIZE]
            ],
            "error": None,
            "fetched_at": time.time(),
        }


def start(user_id: int, cfg: dict, keywords: list[str]) -> None:
    """Kick off a preview unless one is running or a fresh one is cached."""
    with _lock:
        current = _state.get(user_id)
        if current:
            if current["state"] == "running":
                return
            if time.time() - current.get("fetched_at", 0) < CACHE_TTL_SECONDS:
                return
        _state[user_id] = {"state": "running", "fetched_at": time.time()}

    threading.Thread(
        target=_worker, args=(user_id, cfg, keywords), daemon=True
    ).start()


def status(user_id: int) -> dict:
    with _lock:
        current = _state.get(user_id)
    if not current:
        return {
            "state": "idle",
            "total": 0,
            "matched": 0,
            "sources_ok": 0,
            "sources_total": 0,
            "sample": [],
            "error": None,
        }
    return {
        "state": current["state"],
        "total": current.get("total", 0),
        "matched": current.get("matched", 0),
        "sources_ok": current.get("sources_ok", 0),
        "sources_total": current.get("sources_total", 0),
        "sample": current.get("sample", []),
        "error": current.get("error"),
    }
```

- [ ] **Step 4: Add the routes**

Append to `server/onboarding.py`:

```python
# --- Chapter 5: live job inventory, no LLM ------------------------------------

@router.post("/preview-jobs")
def start_preview_jobs(user: User = Depends(require_user)) -> dict:
    """Kick off the LLM-free scrape behind chapter 5.

    Fires while the user is still in chapter 4, so the count is usually ready by
    the time they arrive. Returns immediately either way; the client polls.
    """
    from . import job_preview

    cfg = load_config(user) or {}
    paths = paths_for(user)
    keywords = list((cfg.get("search") or {}).get("keywords") or [])
    if not keywords:
        told, resume_text = _intake_corpus(paths)
        keywords = list(
            extract_search_terms(
                told, resume_text, vocabulary=set(_vocabulary())
            ).keywords
        )
    job_preview.start(user.id, cfg, keywords)
    return {"state": "running"}


@router.get("/preview-jobs")
def get_preview_jobs(user: User = Depends(require_user)) -> dict:
    from . import job_preview

    return job_preview.status(user.id)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_job_preview.py -q`
Expected: 6 passed

The threading is real, so if a test is flaky the cause is the worker not having finished. The worker is started synchronously inside the request and the fake `_fetch` returns instantly, so it should not be — investigate rather than adding a sleep.

- [ ] **Step 6: Commit**

```bash
git add server/job_preview.py server/onboarding.py tests/test_job_preview.py
git commit -m "feat: live job preview for chapter 5, zero tokens"
```

---

### Task 4: Enrichment plan enumeration

**Files:**
- Create: `server/enrichment.py`
- Modify: `server/onboarding.py` (one route)
- Test: `tests/test_enrichment.py`

**Interfaces:**
- Consumes: `server.intake.list_drafts`, `read_notes`, `read_parked_resume`; `server.deps.paths_for`.
- Produces:
  - `plan(user: User) -> list[dict]` — ordered, each `{"id", "label", "ridge"}`
  - `GET /api/onboarding/enrich/plan` → `{"steps": [...]}`

Step ids: `resume`, `story:<slug>` (one per draft), `bio`, `search`. A step appears only when its input exists and its output does not — so the plan is empty for a user with nothing parked, and shrinks as steps complete.

- [ ] **Step 1: Write the failing test**

Create `tests/test_enrichment.py`:

```python
"""The enrichment cascade.

Capture and enrichment are separate passes because the journey runs before the
user has a key. These tests pin the two properties that makes that safe: steps
are idempotent, and drafts are moved rather than deleted.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server.db as db
import src.providers as providers
from server.intake import park_resume, save_draft_story, save_notes
from server.user_paths import UserPaths

from .conftest import make_engine, register


class _FakeProvider:
    name = "fake"

    def json_call(self, system, user, max_tokens=2000, *, schema=None):
        if "keywords" in (user or "").lower() or "keywords" in (system or "").lower():
            return {"keywords": ["backend engineer", "platform engineer"]}
        return {
            "title": "A story",
            "tags": ["backend", "python"],
            "role_fit": ["swe"],
            "company_fit": ["startup"],
            "one_liner": "Did a thing that mattered.",
            "body": "Context. What I did. What mattered. Outcome.",
            "name": "Jane Doe",
            "email": "jane@example.com",
            "experience": [],
            "education": [],
            "projects": [],
            "skills": [],
        }

    def text_call(self, system, user, max_tokens=1000):
        return "I write plainly and care about shipping.\n"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, "engine", engine)
    fake = _FakeProvider()
    monkeypatch.setattr(providers, "get_provider_chain", lambda cfg: [fake])
    monkeypatch.setattr(providers, "get_provider", lambda name, cfg, **k: fake)
    monkeypatch.setattr(providers, "get_task_chains", lambda cfg: {})
    from server.app import app

    with TestClient(app) as c:
        register(c, "a@example.com")
        yield c


@pytest.fixture()
def paths():
    return UserPaths(user_id=1).ensure()


def test_plan_is_empty_when_nothing_was_captured(client):
    r = client.get("/api/onboarding/enrich/plan")
    assert r.status_code == 200, r.text
    assert r.json()["steps"] == []


def test_parked_resume_produces_a_resume_step(client, paths):
    park_resume(paths, "Jane Doe\nSenior Backend Engineer\nAcme, 2020-2024")
    ids = [s["id"] for s in client.get("/api/onboarding/enrich/plan").json()["steps"]]
    assert "resume" in ids


def test_each_draft_produces_its_own_step(client, paths):
    save_draft_story(paths, "One", "first body")
    save_draft_story(paths, "Two", "second body")
    ids = [s["id"] for s in client.get("/api/onboarding/enrich/plan").json()["steps"]]
    assert "story:one" in ids
    assert "story:two" in ids


def test_notes_produce_a_bio_step(client, paths):
    save_notes(paths, "I care about shipping things people use.")
    ids = [s["id"] for s in client.get("/api/onboarding/enrich/plan").json()["steps"]]
    assert "bio" in ids


def test_search_step_appears_once_there_is_any_material(client, paths):
    save_notes(paths, "backend work")
    ids = [s["id"] for s in client.get("/api/onboarding/enrich/plan").json()["steps"]]
    assert "search" in ids


def test_a_step_disappears_once_its_output_exists(client, paths):
    park_resume(paths, "Jane Doe\nSenior Backend Engineer")
    paths.resume_path.write_text("name: Jane Doe\n", encoding="utf-8")
    ids = [s["id"] for s in client.get("/api/onboarding/enrich/plan").json()["steps"]]
    assert "resume" not in ids


def test_every_step_names_the_ridge_it_fills(client, paths):
    park_resume(paths, "Jane Doe")
    save_draft_story(paths, "One", "body")
    for step in client.get("/api/onboarding/enrich/plan").json()["steps"]:
        assert step["ridge"]
        assert step["label"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_enrichment.py -q`
Expected: FAIL — 404 on `/api/onboarding/enrich/plan`

- [ ] **Step 3: Write minimal implementation**

Create `server/enrichment.py`:

```python
"""Turn captured raw material into real master data, one step at a time.

The journey deliberately runs before the user has an API key, so every AI
transformation lands here instead of inline at capture time. That separation
also means capture never fails because a model was down, a key was wrong or a
quota was hit — and each step below is independently retryable.

The client drives the steps one at a time so that ridge animation reflects real
progress rather than a timed fake, and so a single failure is retryable in place
without restarting the cascade.
"""
from __future__ import annotations

import logging

from .db import User
from .deps import paths_for
from . import intake as intake_store

log = logging.getLogger("server.enrichment")


def plan(user: User) -> list[dict]:
    """Ordered, pending enrichment steps.

    A step appears only when its input exists and its output does not, which is
    what makes the whole cascade idempotent: re-running it after a partial
    failure simply produces a shorter plan.
    """
    paths = paths_for(user)
    steps: list[dict] = []

    parked = intake_store.read_parked_resume(paths).strip()
    if parked and not paths.resume_path.exists():
        steps.append(
            {"id": "resume", "label": "Reading your resume", "ridge": "resume"}
        )

    drafts = intake_store.list_drafts(paths)
    for index, draft in enumerate(drafts, start=1):
        steps.append(
            {
                "id": f"story:{draft['slug']}",
                "label": f"Shaping “{draft['title']}”",
                "ridge": f"story_{min(index, 3)}",
            }
        )

    notes = intake_store.read_notes(paths).strip()
    if notes and not paths.bio_path.exists():
        steps.append({"id": "bio", "label": "Learning your voice", "ridge": "voice"})

    if parked or notes or drafts:
        steps.append(
            {"id": "search", "label": "Working out what to look for", "ridge": "search"}
        )

    return steps
```

- [ ] **Step 4: Add the route**

Append to `server/onboarding.py`:

```python
# --- Chapter 6: the enrichment cascade ---------------------------------------

@router.get("/enrich/plan")
def enrich_plan(user: User = Depends(require_user)) -> dict:
    from . import enrichment

    return {"steps": enrichment.plan(user)}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_enrichment.py -q`
Expected: 7 passed

- [ ] **Step 6: Commit**

```bash
git add server/enrichment.py server/onboarding.py tests/test_enrichment.py
git commit -m "feat: enumerate pending enrichment steps"
```

---

### Task 5: Enrichment step execution

**Files:**
- Modify: `server/enrichment.py`
- Modify: `server/onboarding.py` (one route)
- Test: `tests/test_enrichment.py`

**Interfaces:**
- Consumes: `src.content_studio.import_resume`, `master_resume_to_yaml`, `generate_story`, `story_dict_to_markdown`, `slugify`, `load_taxonomy`, `suggest_keywords`, `tweak_content`; `server.studio._call`, `_resolve_chain`.
- Produces:
  - `run_step(user: User, step_id: str, *, force: bool = False) -> dict` — `{"id", "done", "skipped", "ridge", "result"}`
  - `POST /api/onboarding/enrich/step` — body `{"step_id": str, "force": bool}` → that dict

**This is the only place in plans 1 and 2 that calls a provider.** It runs after the user connects a key, which is what licenses it.

Signatures confirmed against the current source:
- `import_resume(text: str, *, provider) -> dict`
- `master_resume_to_yaml(data: dict) -> str`
- `generate_story(description: str, *, provider, taxonomy: str = "", existing_titles: list[str] | None = None) -> dict`
- `story_dict_to_markdown(story: dict) -> str`
- `suggest_keywords(description: str, *, provider, existing: list[str] | None = None) -> list[str]`
- `tweak_content(kind: str, text: str, instruction: str, *, provider, stories=None) -> str`
- `load_taxonomy(stories_dir) -> str`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_enrichment.py`:

```python
def _run(client, step_id, force=False):
    r = client.post(
        "/api/onboarding/enrich/step",
        json={"step_id": step_id, "force": force},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_resume_step_writes_resume_yaml(client, paths):
    park_resume(paths, "Jane Doe\nSenior Backend Engineer\nAcme, 2020-2024")
    out = _run(client, "resume")
    assert out["done"] is True
    assert paths.resume_path.exists()


def test_resume_step_is_idempotent(client, paths):
    park_resume(paths, "Jane Doe\nSenior Backend Engineer")
    _run(client, "resume")
    paths.resume_path.write_text("name: Untouched\n", encoding="utf-8")
    out = _run(client, "resume")
    assert out["skipped"] is True
    assert "Untouched" in paths.resume_path.read_text(encoding="utf-8")


def test_force_reruns_a_completed_step(client, paths):
    park_resume(paths, "Jane Doe\nSenior Backend Engineer")
    _run(client, "resume")
    paths.resume_path.write_text("name: Untouched\n", encoding="utf-8")
    out = _run(client, "resume", force=True)
    assert out["skipped"] is False
    assert "Untouched" not in paths.resume_path.read_text(encoding="utf-8")


def test_story_step_writes_a_real_story(client, paths):
    save_draft_story(paths, "One", "we shipped it on a Friday")
    out = _run(client, "story:one")
    assert out["done"] is True
    real = [p for p in paths.stories_dir.glob("*.md") if not p.name.startswith("_")]
    assert len(real) == 1


def test_story_step_moves_the_draft_to_consumed_rather_than_deleting_it(client, paths):
    save_draft_story(paths, "One", "we shipped it on a Friday")
    _run(client, "story:one")
    assert list(paths.intake_stories_dir.glob("*.md")) == []
    consumed = list(paths.intake_consumed_dir.glob("*.md"))
    assert len(consumed) == 1
    assert "we shipped it on a Friday" in consumed[0].read_text(encoding="utf-8")


def test_bio_step_writes_bio_md(client, paths):
    save_notes(paths, "I care about shipping things people use.")
    out = _run(client, "bio")
    assert out["done"] is True
    assert paths.bio_path.exists()


def test_search_step_proposes_without_writing_config(client, paths):
    save_notes(paths, "backend work in python")
    before = client.get("/api/config").json()["text"]
    out = _run(client, "search")
    assert out["result"]["keywords"]
    after = client.get("/api/config").json()["text"]
    assert before == after


def test_an_unknown_step_id_is_a_400(client):
    r = client.post(
        "/api/onboarding/enrich/step", json={"step_id": "nonsense", "force": False}
    )
    assert r.status_code == 400


def test_a_missing_draft_is_a_404(client):
    r = client.post(
        "/api/onboarding/enrich/step", json={"step_id": "story:ghost", "force": False}
    )
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_enrichment.py -q`
Expected: FAIL — 404 on `/api/onboarding/enrich/step`

- [ ] **Step 3: Write minimal implementation**

Append to `server/enrichment.py`:

```python
from fastapi import HTTPException

from src.content_studio import (
    generate_story,
    import_resume,
    load_taxonomy,
    master_resume_to_yaml,
    story_dict_to_markdown,
    suggest_keywords,
    tweak_content,
)

from .intake import slugify
from .studio import _call, _resolve_chain


def _existing_titles(paths) -> list[str]:
    from src.reference_loader import load_stories

    if not paths.stories_dir.exists():
        return []
    return [str(s.get("title") or "") for s in load_stories(paths.stories_dir)]


def _consume_draft(paths, slug: str) -> None:
    """Move a used draft aside instead of deleting it.

    The draft is the user's own words. If enrichment produced something they
    dislike, the raw material has to still be there.
    """
    source = paths.intake_stories_dir / f"{slug}.md"
    if not source.exists():
        return
    paths.intake_consumed_dir.mkdir(parents=True, exist_ok=True)
    target = paths.intake_consumed_dir / source.name
    counter = 2
    while target.exists():
        target = paths.intake_consumed_dir / f"{source.stem}-{counter}.md"
        counter += 1
    source.replace(target)


def run_step(user: User, step_id: str, *, force: bool = False) -> dict:
    """Run one enrichment step. Idempotent unless ``force``."""
    paths = paths_for(user)
    chain = _resolve_chain(user, None)

    if step_id == "resume":
        if paths.resume_path.exists() and not force:
            return {"id": step_id, "done": True, "skipped": True, "ridge": "resume", "result": None}
        parked = intake_store.read_parked_resume(paths).strip()
        if not parked:
            raise HTTPException(404, "no parked resume to import")
        data = _call(chain, lambda p: import_resume(parked, provider=p))
        paths.resume_path.write_text(master_resume_to_yaml(data), encoding="utf-8")
        return {"id": step_id, "done": True, "skipped": False, "ridge": "resume", "result": None}

    if step_id.startswith("story:"):
        slug = step_id.split(":", 1)[1]
        draft = next(
            (d for d in intake_store.list_drafts(paths) if d["slug"] == slug), None
        )
        if draft is None:
            raise HTTPException(404, f"no draft story '{slug}'")
        taxonomy = load_taxonomy(paths.taxonomy_dir)
        story = _call(
            chain,
            lambda p: generate_story(
                draft["body"],
                provider=p,
                taxonomy=taxonomy,
                existing_titles=_existing_titles(paths),
            ),
        )
        name = slugify(str(story.get("title") or draft["title"]))
        target = paths.stories_dir / f"{name}.md"
        counter = 2
        while target.exists():
            target = paths.stories_dir / f"{name}-{counter}.md"
            counter += 1
        target.write_text(story_dict_to_markdown(story), encoding="utf-8")
        _consume_draft(paths, slug)
        return {
            "id": step_id,
            "done": True,
            "skipped": False,
            "ridge": "story_1",
            "result": {"title": story.get("title"), "file": target.name},
        }

    if step_id == "bio":
        if paths.bio_path.exists() and not force:
            return {"id": step_id, "done": True, "skipped": True, "ridge": "voice", "result": None}
        notes = intake_store.read_notes(paths).strip()
        if not notes:
            raise HTTPException(404, "no notes to derive a voice from")
        text = _call(
            chain,
            lambda p: tweak_content(
                "bio",
                notes,
                "Turn this into a short voice guide describing how this person "
                "writes and what they care about. Keep their own words and "
                "specifics wherever possible. Invent nothing.",
                provider=p,
            ),
        )
        paths.bio_path.write_text(text, encoding="utf-8")
        return {"id": step_id, "done": True, "skipped": False, "ridge": "voice", "result": None}

    if step_id == "search":
        told = intake_store.read_notes(paths)
        drafts = intake_store.list_drafts(paths)
        corpus = "\n\n".join(
            [told, *(d["body"] for d in drafts), intake_store.read_parked_resume(paths)]
        ).strip()
        if not corpus:
            raise HTTPException(404, "nothing captured to work from")
        keywords = _call(chain, lambda p: suggest_keywords(corpus, provider=p))
        # Proposes only. The user's chips are theirs; writing config here would
        # overwrite a correction they already made in chapter 4.
        return {
            "id": step_id,
            "done": True,
            "skipped": False,
            "ridge": "search",
            "result": {"keywords": keywords},
        }

    raise HTTPException(400, f"unknown enrichment step '{step_id}'")
```

- [ ] **Step 4: Add the route**

Append to `server/onboarding.py`:

```python
class EnrichStepBody(BaseModel):
    step_id: str
    force: bool = False


@router.post("/enrich/step")
def enrich_step(
    body: EnrichStepBody, user: User = Depends(require_user)
) -> dict:
    from . import enrichment

    return enrichment.run_step(user, body.step_id, force=body.force)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_enrichment.py -q`
Expected: 16 passed

- [ ] **Step 6: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: all pass (≥393), scope lint green.

- [ ] **Step 7: Commit**

```bash
git add server/enrichment.py server/onboarding.py tests/test_enrichment.py
git commit -m "feat: run enrichment steps idempotently, preserving drafts"
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| Nine formation ridges, completing at 100% | 1 |
| Draft = half-filled ridge, completes during cascade | 1, 5 |
| Depth phase = coverage vs `_INDEX.md` taxonomy | 1 |
| `GET /api/profile/strength` | 1 |
| Gemini recommended, DeepSeek not first | 2 |
| Setup steps ≤3 lines, deep links, no numbers | 2 |
| `verified_on` + link checker not a unit test | 2 |
| `GET /api/providers/setup` | 2 |
| `POST/GET /preview-jobs`, cached, degrades gracefully | 3 |
| Chapter 5 costs zero tokens | 3 |
| `GET /enrich/plan` | 4 |
| `POST /enrich/step`, idempotent, `force` | 5 |
| Drafts moved to `consumed/`, never deleted | 5 |
| `search` proposes, never writes | 5 |

**Known simplification, stated rather than hidden:** `_fetch` reports `sources_ok == sources_total` because `fetch_all` swallows per-source failures and returns no per-source outcome. The status field exists and the UI copy ("across 6 of 9 boards") is supported the moment the scraper layer reports it. Threading that through `fetch_all` is a separate change and does not belong in this plan.

**Ridge attribution for story steps** is approximate: `run_step` returns `ridge: "story_1"` for every story rather than computing which of the three slots it fills. The client re-reads `/api/profile/strength` after each step anyway, so the authoritative state comes from there; the field is a hint for optimistic animation.
