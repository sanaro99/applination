# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

**Applination** — an AI-assisted job application pipeline (internships, new-grad, and full-time) for any user. Daily run fetches job postings from 8 public APIs, uses LLMs to rank jobs against the candidate's background (0–100 fit score), tailors resumes, and writes cover letters for top matches. Outputs a dated Excel tracker.

The tool is single-tenant (one profile per install) but **not tied to any one person**: the candidate's identity is derived from `master_data/resume.yaml` via `src/profile.py` (never hardcoded in prompts), and a web **onboarding flow** sets up a new user (provider key → contact → resume upload+AI-extract → AI interview for stories/bio → search prefs). Personal data + API keys live in gitignored files (`config.yaml`, `master_data/resume.yaml`, `master_data/bio.md`, `master_data/stories/*.md`, `master_data/cover_letters/examples/*`); committed templates live in `config.example.yaml` and `master_data/templates/`.

## Commands

```bash
# Setup
python -m venv .venv
.venv\Scripts\activate           # Windows
pip install -r requirements.txt

# Dry run — fetch + rank only, no tailoring or LLM resume calls
python -m src.main --dry-run

# Full run
python -m src.main

# Skip PDF conversion (produce .docx only)
python -m src.main --no-pdf

# Tweak a generated resume
python -m src.tweak output/2026-04-24/Company_Role/resume.docx "Emphasize LangGraph work"
python -m src.tweak resume.docx "more ML focus" --provider gemini
python -m src.tweak resume.docx --interactive

# Web app (FastAPI + Next.js, replaces the old Streamlit app.py)
.\scripts\dev.ps1                         # starts both: API :8000, web :3000
python -m uvicorn server.app:app --reload --port 8000   # API only
cd web && npm run dev                                    # web only
```

## Commits & version control

- Commit and push after every meaningful feature, fix, or doc change — don't batch unrelated changes.
- Use conventional-commit prefixes: `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`.
- Personal data is gitignored — never commit `config.yaml`, `master_data/resume.yaml`,
  `master_data/bio.md`, `master_data/stories/*.md` (except `_INDEX.md`), or
  `master_data/cover_letters/examples/*` (except `.gitkeep`).
- Remote: `https://github.com/sanaro99/applination` (branch: `main`)
- After committing: `git push origin main`

## Web architecture

- **`server/`** — FastAPI bridge in front of `src/`. Routers: `runs.py` (start a run + SSE stream; persists the ranked pool + applications from `on_event`), `applications.py` (CRUD + status + tags + deadline; bulk status/tag update + CSV export; `_migrate()` in `db.py` ALTERs existing tables to add new columns since `create_all` won't), `single_job.py` (URL/manual extract + generate; `start_generation()` + the worker are reused by the ranked-rescue flow), `config_api.py` (yaml + master-data text editors), `tweak.py` (resume tweak via `src/tweak.apply_tweak` + inline cover-letter GET/PUT that re-renders docx/pdf), `stats.py` (aggregates), `ranked.py` (job triage: list a run's full scored pool, generate/"rescue" a non-selected job, **dismiss** a job → hidden from future runs via cross-run dedup), `ops.py` (provider connectivity test via a tiny real call + `GET /api/compare` two-run diff + structured `GET/PUT /api/llm-config` for per-workflow LLM routing), `chat.py` (**Prepwork** — Coach chat + Mock interview + Essay drafter + answer bank; see below), `studio.py` (LLM-assisted master-data authoring — generate a story / tweak story/bio/resume, preview-only), `inbox.py` + `reminders.py` (**Close the loop** — see below). Note: the provider layer exposes no token usage, so there is no $/token tracking — "insight" is run timing/throughput/score comparison only. SQLite via SQLModel at `data/app.db` indexes runs, applications, the ranked pool (`RankedJob`), and Prepwork (`ChatSession`/`ChatMessage`/`SavedAnswer`); output folder is still source-of-truth for documents (served via static mount `/files/*`).
- **Close the loop (`server/inbox.py` + `server/reminders.py` + `server/gmail_auth.py`, engine in `src/inbox.py` / `src/gmail_oauth.py` / `src/gmail_api.py` / `src/calendar_feed.py` / `src/digest.py`)** — post-application lifecycle. **Cross-run dedup**: each run is given an `excluded_keys` set (built in `runs.py._build_excluded_keys` from every `Application` + every dismissed `RankedJob`, keyed by `src.scrapers.dedupe_key(company,title)`); `rank_and_filter(excluded_keys=...)` and the triage pool drop those so already-applied/dismissed jobs are never re-tailored or re-surfaced. **Gmail OAuth**: `inbox.client_id`/`client_secret` (a Google Cloud OAuth client the user creates) live in config.yaml; the access/refresh token + connected account email live in the `Setting` table (`server/gmail_auth.py`, never config.yaml). `GET /api/inbox/oauth/authorize` redirects to Google's consent screen (opened in a popup from the Config page's `GmailConnectCard`); `GET /api/inbox/oauth/callback` exchanges the code, stores the token, and `postMessage`s the opener before closing. **Inbox sync**: `src/gmail_api.GmailApiScanner` reads Gmail via the Gmail API (`messages.list` + `messages.get(format="raw")`, parsed with `src/inbox._parse_message` — same RFC822 parsing IMAP used), matches messages to in-flight applications by company. Classification is a deliberate exception to "all LLM calls go through `src/providers/`": `GET /api/inbox/sync/candidates` fetches + matches only (no LLM call) and returns candidates to the browser; `web/lib/webllm-classify.ts` runs the actual auto_ack/interview/rejection/offer/other classification **in-browser via WebLLM** (`@mlc-ai/web-llm`, a small local model, no cloud call) since it's a simple 5-category label that doesn't need a full cloud LLM; `POST /api/inbox/sync/apply` takes one browser-classified message at a time, validates/clamps it (`src/inbox.normalize_classification` — never trusts client values directly) and applies conservative **forward-only** status transitions (offer never downgraded; gated by `min_confidence`; idempotent via a processed-id set in `Setting`); sets `interview_at`/`applied_at`/`last_email_at`, always leaves a `notes` breadcrumb. `components/inbox-sync.tsx` drives the whole fetch→load-model→classify-one-by-one loop and renders live progress in a `Sheet` (not just a spinner) — since the browser runs the loop itself, no backend SSE/event-bus is needed for this. **Reminders**: `GET /api/calendar.ics` serves a live iCalendar feed (deadlines + interviews) any calendar app can import; `src/digest.py` builds the digest HTML/text and `src/gmail_api.send_via_gmail_api` sends it through the same OAuth connection (no SMTP/app password). Web: `components/inbox-sync.tsx` (Applications header), `components/gmail-connect-card.tsx` (Config page), `components/reminders-card.tsx` (dashboard).
- **Prepwork (`server/chat.py` + `server/coach_context.py`)** — a profile-grounded conversational assistant. `ChatSession.mode` is `chat` (Coach) or `interview` (mock interview: one question at a time → coached feedback + model answer + next question; `POST /sessions/{id}/kickoff` seeds the first question). `coach_context.py` assembles `(system, user)` prompts from `bio.md` + `resume.yaml` + matched stories (`reference_loader.match_stories`), reusing the cover-letter voice + anti-fabrication "BINDING" language; it also builds the interview-kickoff and essay prompts. Essay drafter is one-shot (`POST /api/chat/essay`). Good replies save to the answer bank (`SavedAnswer`) and can attach to an application's `answers.md`. All three flows route through `_run_chain(task=...)` → the per-task provider chain (`coach`/`interview`/`essay`), falling back to the global chain. **Send-and-wait, no streaming** (no provider streams today).
- **`src/pipeline.py`** — `run_pipeline(cfg, *, dry_run, no_pdf, no_cache, on_event)` is the importable orchestrator. CLI `python -m src.main` delegates to it. The `on_event` callback fans progress events through `server/events.py` to all SSE subscribers; it also emits a `rank_pool` event (full scored candidate list, capped at 200, selected jobs always included) used to populate the triage view — fires in dry-run too.
- **`web/`** — Next.js 16 (App Router, Turbopack) + Tailwind v4 + shadcn/ui + MagicUI. Nav groups: **Workspace** (`/` dashboard + upcoming-deadlines + **Reminders** card (calendar/digest), `/run` live SSE progress, `/applications` table+kanban / detail + **Sync inbox** button, `/single` 3-step wizard), **Prepwork** (`/coach` chat, `/interview` mock interview, `/essay` drafter — `/coach` + `/interview` share `components/coach/conversation-workspace.tsx` parametrized by `mode`; assistant text rendered with `react-markdown`; per-conversation job grounding via a searchable `ground-picker.tsx`; answer-bank sheet), **Insights** (`/runs` + `/runs/[id]` history/log/event-timeline + **Ranked jobs** triage tab, `/runs/compare` two-run diff, `/stats` Recharts), **Setup** (`/config` raw config.yaml editor + provider tests, `/workflows` visual per-workflow LLM routing editor, `/master-data` resume.yaml + bio.md + stories with **"New story" from a description** and an **"Improve with AI"** panel on each tab via `components/ai-assist.tsx`). Application detail has a resume **version diff** (`lib/resume-diff.ts`) and inline cover-letter editing. Server state via TanStack Query, ephemeral UI via Zustand. Theme via next-themes (dark default; unified indigo accent — all chart/badge colors flow through CSS tokens in `globals.css`, light mode works). Cmd+K palette. A mounted `RunActivityWatcher` toasts when a background run finishes.

**Scheduling:**
- Linux/macOS: `bash scripts/setup_cron.sh`
- Windows: `.\scripts\setup_task_scheduler.ps1` (omit `-Time` to auto-default into off-peak; `-Time "HH:mm"` to override)
- **Off-peak default:** DeepSeek (the default provider) bills ~50% less during 16:30–00:30 GMT. Both scripts default the daily run to the local equivalent of 20:00 GMT so it lands in that window automatically, and warn if you pick a peak-hour time (`-FullPrice` silences the PS1 warning).

## Architecture

### Data Flow

```
config.yaml (API keys, search params, LLM config, user info)
      ↓
src/main.py: fetch_all() → 8 scrapers → Job list
      ↓
Tailor.rank_jobs() → LLM batches (~15 jobs/call) → scores → filter by threshold + diversity
      ↓
For each top job:
  tailor_resume() → structured JSON → build_resume_onepage() → resume.docx/pdf
  match_stories() + match_example_letter() → personalization inputs
  write_cover_letter() → cover_letter.docx/pdf
  Save job.json + resume.json snapshots
      ↓
build_tracker() → output/YYYY-MM-DD/apps_YYYY-MM-DD.xlsx
```

### Key Modules

**`src/main.py`** — Orchestrator. Loads config, calls all scrapers, drives the rank→tailor→output loop.

**`src/tailor.py`** — LLM interactions: `rank_jobs()`, `tailor_resume()`, `write_cover_letter()`. Uses `RESUME_CONSTRAINTS` dict to enforce one-page limits. Preserves the candidate's full-time (non-internship) roles. Strips em dashes for ATS compatibility. **Identity is data-driven, never hardcoded**: the summary-identity guards (`_normalize_summary_identity`, `_ensure_core_experience`) take a `profile` dict.

**`src/profile.py`** — `derive_profile(master)` builds the candidate identity (`identity_titles`, `seniority` student/new-grad/professional, `preserve_fulltime`, `education_close`) from `resume.yaml`'s experience/education, with an optional top-level `profile:` override block in `resume.yaml`. Threaded through `tailor_graph.py` (the tailoring prompt's IDENTITY/seniority/education rules are built from it) and the `tailor.py` guards. This is what makes the engine work truthfully for anyone, not just one person.

**`src/resume_builder.py`** — Renders one-page ATS-safe `.docx` from the tailored JSON. Uses a line-count estimator; if overflow predicted, iteratively drops lowest-priority content (coursework → 3rd project → extra bullets). Default margins: 0.25" L/R, 0.19" T/B, Times New Roman 10pt.

**`src/providers/`** — LLM abstraction layer. `base.py` defines `LLMProvider` ABC (`text_call`, `json_call(schema=...)`). `factory.py` exposes `get_provider()`, `get_provider_with_fallback()`, `get_provider_chain()`, `get_task_chains()` (per-task chains keyed by `_TASK_NAMES`), and `try_chain()` (per-call fallback on quota/any error). Implementations: `claude_provider.py`, `gemini_provider.py`, `ollama_provider.py`, `nim_provider.py`, `openrouter_provider.py`, `deepseek_provider.py`, `mistral_provider.py`. All non-LLM code uses this abstraction — never import Anthropic/OpenAI directly outside providers/.

**`src/content_studio.py`** — LLM-assisted master-data authoring (used by `server/studio.py` + `server/onboarding.py`). `generate_story()` drafts a structured story from a description via `json_call(schema=STORY_SCHEMA)` (`src/schemas/story_schema.py`), `story_dict_to_markdown()` renders frontmatter + body, `tweak_content(kind, text, instruction)` revises story/bio/resume by instruction. `import_resume(text)` extracts a raw resume (pasted or PDF/DOCX text) into the master-resume shape via `MASTER_RESUME_SCHEMA`, and `master_resume_to_yaml()` renders it. Grounded + anti-fabrication, mirroring `tweak.py`.

**`server/onboarding.py`** — first-run setup endpoints (router prefix `/api/onboarding`): `GET /status` (what's still missing + `can_run`), `POST /complete`/`/reset` (an `onboarded` flag in the `Setting` table), structured config writers `PUT /user`/`/provider`/`/search` (round-tripped through ruamel via `deps.update_config` so comments survive), and `POST /resume-import` (multipart PDF/DOCX/TXT) / `/resume-import-text`. The web wizard lives at `web/app/onboarding/` and is gated by `web/components/onboarding-gate.tsx` (redirects a not-set-up install). On a fresh clone `deps.load_config()` seeds `config.yaml` from `config.example.yaml`.

**`src/scrapers/`** — All scrapers return the unified `Job` dataclass from `schema.py`. `simplify_github.py` pulls the Pitt CSC GitHub list (~1100 roles). `greenhouse.py` queries 20+ hardcoded company slugs.

**`src/reference_loader.py`** — Loads `master_data/stories/*.md` (YAML frontmatter + body) and example cover letters. `match_stories()` scores by tag overlap (×2) + keyword hits (×1), returns top-k.

**`src/tweak.py`** — Interactive CLI for post-generation resume adjustments. Reads `resume.json` + `job.json` from output folder, applies LLM instruction, saves versioned output (`resume.v2.docx`, etc.).

### Master Data

- `master_data/resume.yaml` — Full master resume; source of truth for all content
- `master_data/bio.md` — Voice/tone reference injected into cover letter prompts
- `master_data/stories/*.md` — narrative stories with YAML frontmatter (`tags`, `role_fit`, `company_fit`, `one_liner`); `_INDEX.md` holds the tag/role/company taxonomy. Stories can be generated/edited from the web `/master-data` page or onboarding (see `src/content_studio.py`). **Personal master data is gitignored** (`resume.yaml`, `bio.md`, `stories/*.md`, `cover_letters/examples/*`); committed `*.example` templates live in `master_data/templates/`, and `guidelines/*` + `stories/_INDEX.md` are committed (generic).
- `master_data/cover_letters/examples/` — Past cover letters as PDFs; convert to `.md` with YAML frontmatter to enable example-matching
- `master_data/guidelines/*.md` — resume/cover-letter writing guidelines matched per-role (`reference_loader.load_guidelines`/`match_guidelines`)

### Configuration (`config.yaml`)

- `user:` — contact info used in rendered documents
- `search:` — keywords, `min_match_score` (default 55), `max_jobs_per_day` (default 50), location filters
- `sources:` — enable/disable each scraper; Greenhouse slugs listed here
- `llm:` — global `primary` + `fallbacks`; each provider block (`claude`/`gemini`/`ollama`/`nim`/`openrouter`/`deepseek`/`mistral`) has `api_key` + `model`. `llm.tasks.<task>` gives per-workflow overrides (`primary`/`fallbacks`/`models: {provider: model}`); task keys are `ranking`, `tailoring`, `tailoring_premium`, `cover_letter`, `critique`, `answer_questions`, `coach`, `interview`, `essay`, `content_studio` (any omitted task inherits the global chain). The `/workflows` page edits this visually via `PUT /api/llm-config`, which writes through **ruamel.yaml** to preserve comments + other sections (`server/deps.update_llm_config`). Also `critique_cover_letters`, `critique_top_n`, `tailoring_premium_top_n`.
- `output:` — root dir, font, font size, margins, `produce_pdf` flag
- `inbox:` — Close-the-loop inbox sync (disabled by default). `client_id`/`client_secret` (a Google Cloud OAuth client — connect from the Config page; the token itself lives in the `Setting` DB table, not here), `redirect_uri`, `scan_days`, `min_confidence` (status-change threshold), `auto_update_status`, `max_classifications` (per-sync LLM cost cap).
- `reminders:` — `digest_enabled`, `digest_to` (defaults to `user.email`), `deadline_window_days`, `follow_up_days`. Digest sends via the same Gmail OAuth connection as inbox sync (`src/gmail_api.send_via_gmail_api`).

API keys can also be set via env vars: `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`, `MISTRAL_API_KEY`.

## PDF Conversion

Requires Microsoft Word (Windows/macOS) or LibreOffice (`soffice` on PATH for Linux). If neither is available, use `--no-pdf`.

## Cost Reference

- Claude Haiku: ~$0.10–0.30/run (30 jobs)
- Gemini Flash / Ollama: effectively free
- DeepSeek (default): cheapest cloud path; ranking cost is ~fixed per run (scales with jobs *fetched*, not `max_jobs_per_day`), tailoring+cover scale with selected count. **Off-peak (16:30–00:30 GMT): ~50% off** — the scheduler scripts default into this window. No async batch API; use off-peak + prefix caching instead (batch APIs on Claude/Gemini/Mistral give the same 50% but with up to 24h latency, which conflicts with same-run document output).
