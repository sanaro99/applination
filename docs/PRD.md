# Applination — Product Requirements Document

**Version:** 1.0  
**Date:** June 2026  
**Status:** Living document  

---

## 1. Product Overview

### 1.1 Summary

Applination is a self-hosted, AI-assisted job application pipeline for individual job seekers. It automates the most time-consuming parts of applying for jobs: discovering new postings, ranking them against the user's background, tailoring resumes, writing cover letters, and tracking application status — all from a single web interface.

### 1.2 Problem Statement

Applying for jobs at scale requires:
- Monitoring 8+ job boards daily for new postings
- Manually assessing fit for dozens of roles at a time
- Rewriting resumes and cover letters for each application
- Tracking which applications are pending, active, or completed

This work takes hours per week and is highly repetitive. Applination automates the entire pipeline with LLM-powered personalization while ensuring outputs stay grounded in the candidate's real experience.

### 1.3 Design Philosophy

- **Single-tenant, not tied to one person.** One install per user, but the candidate identity is fully derived from `master_data/resume.yaml` — nothing is hardcoded. A new user sets up their profile through the onboarding wizard.
- **Anti-fabrication.** All LLM prompts use explicit BINDING rules that prohibit inventing experience, employers, technologies, or metrics not present in the candidate's material.
- **Local-first, bring-your-own-key.** Runs on the user's machine; API keys are stored locally and never sent to a third party.
- **Output documents are source-of-truth.** The `output/` folder holds all generated `.docx`, `.pdf`, and `.json` artifacts. The database indexes metadata for querying; it never duplicates the document content.

---

## 2. User Personas

**Primary Persona — Active Job Seeker**  
A student, new graduate, or working professional who is applying to 20–100+ positions over a multi-month campaign. They have a solid resume and background but lack the time to manually customize every application. They are comfortable with software setup (Python, npm) but are not necessarily developers.

---

## 3. Core Features

### 3.1 Daily Pipeline Run

The primary workflow. On demand (or via scheduler), the pipeline:

1. **Fetches** job postings from up to 8 configured sources
2. **Ranks** all fetched jobs using an LLM (batch of ~15 per call), producing a 0–100 fit score and reason for each
3. **Filters** by configurable minimum score and diversity heuristics
4. **Tailors** a one-page ATS-safe resume for each top-N job using the candidate's master resume
5. **Matches** the most relevant personal stories and example cover letters
6. **Writes** a personalized cover letter
7. **Generates** answers to supplemental/additional application questions
8. **Saves** a dated Excel tracker (`apps_YYYY-MM-DD.xlsx`) and per-application folder

**Run options:**
- `dry_run` — fetch + rank only, skip all LLM tailoring (no cost)
- `no_pdf` — produce `.docx` only, skip Word/LibreOffice PDF conversion
- `no_cache` — re-tailor even if a cached output exists for this job

**Quality tiers:**  
Top-N jobs (configurable `tailoring_premium_top_n`, default 3) are routed to a premium LLM model for tailoring; remaining jobs use the standard chain.

**Graceful stop:**  
The user can stop a running pipeline in two modes — graceful (finishes the current job and writes the Excel tracker) or immediate (stops after the current LLM call returns).

### 3.2 Single-Job Application

A 3-step wizard for generating materials for one specific job posting:

1. **URL step** — optionally paste a job URL for AI extraction (LinkedIn blocked by design; user pastes manually)
2. **Review step** — edit extracted fields: company, title, location, remote, description, supplemental questions, specific instructions
3. **Generate step** — streams live logs while tailoring; on completion, links directly to the generated documents and the new application record

### 3.3 Application Tracker

A management view of all generated applications.

**Table view:**
- Search by company, role, or tag
- Filter by status
- Inline status update per row
- External link icon to open the original job posting URL
- Bulk status update for selected rows
- CSV export (all or selected)

**Kanban view:** Applications organized by status in draggable columns.

**Application detail page:**
- Resume preview (inline PDF iframe), showing the latest tweaked version
- Cover letter preview with inline text editor (edits regenerate the PDF)
- Answers viewer (supplemental question answers in markdown)
- Job JSON and Resume JSON raw data viewers
- Status, applied date, deadline, tags, and notes (auto-saves with debounce)
- Download links for resume/cover letter in PDF and DOCX formats (served via API so Content-Disposition sets the correct candidate-named filename)
- Link back to the originating run
- Resume version history and diff viewer
- Resume tweak panel (post-generation instruction → new versioned revision)

**Application statuses:**  
`generated` → `applied` → `interviewing` → `rejected` / `offer` / `archived`

### 3.4 Ranked Job Triage

Accessible from the run detail page's **Ranked jobs** tab. Shows the full scored candidate pool from a run (capped at 200, including non-selected jobs).

- Filter by `all / selected / rejected / generated`
- "Rescue" (generate) any non-selected job on demand, which spins up a single-job generation and streams back into the same UI

### 3.5 Prepwork (Coach)

A profile-grounded conversational assistant for interview and application preparation. All three modes share the same master-data context (bio, resume summary, top-3 matched stories) and the same anti-fabrication BINDING rules as the tailoring pipeline.

**Coach (free chat):**  
General career coaching, behavioral question practice, and cover letter/essay drafting. The assistant is contextually aware of the candidate's real background and can optionally be grounded to a specific application's job description.

**Mock Interview:**  
Structured mock interview mode (`mode=interview`). The `POST /sessions/{id}/kickoff` endpoint generates the first question. Each subsequent user message is treated as an answer — the assistant responds with structured feedback (what landed, what to tighten), a model answer in the candidate's voice, and the next question.

**Essay Drafter:**  
One-shot endpoint (`POST /api/chat/essay`). Given an essay prompt, optional word limit, and optional instructions, it generates a grounded draft in the candidate's voice.

**Answer Bank:**  
Saves strong assistant responses as reusable `SavedAnswer` records. Saved answers can be attached to an application's `answers.md`.

**Ground picker:**  
A searchable selector to optionally ground any conversation to a specific application (company + job title context injected into the system prompt).

### 3.6 Insights

**Run History (`/runs`):**  
Table of all past runs with status, timing, and application counts.

**Run Detail (`/runs/[id]`):**  
- Live SSE event stream during active runs (stage progress, per-job status, live log terminal)
- Event timeline for completed runs
- Ranked jobs triage tab (see §3.4)
- Full pipeline log file viewer

**Run Compare (`/runs/compare`):**  
Side-by-side diff of two runs: duration, jobs found, applications created, average score, status breakdown, companies in common, companies unique to each run.

**Stats (`/stats`):**  
Aggregate charts using Recharts: applications by status, applications by source, top companies, daily application count over time, match score distribution.

### 3.7 Master Data Management

The source material the LLM is grounded in. All content lives in `master_data/` and is gitignored (personal data).

**Resume (`master_data/resume.yaml`):**  
Full master resume in structured YAML. Contains experience, education, skills, projects, summary options. The pipeline never directly outputs the master resume — it tailors a one-page subset per job.

**Bio (`master_data/bio.md`):**  
Voice and tone reference. Injected into cover letter and Coach prompts so the LLM writes in the candidate's authentic style.

**Stories (`master_data/stories/*.md`):**  
Narrative STAR-format stories with YAML frontmatter (`tags`, `role_fit`, `company_fit`, `one_liner`). Selected by semantic scoring (tag overlap × 2 + keyword hits × 1) per job. Used in cover letters, answer generation, and Coach responses.

**Cover letter examples (`master_data/cover_letters/examples/`):**  
Past cover letters as `.md` files with YAML frontmatter; matched by overlap for tone reference.

**Guidelines (`master_data/guidelines/*.md`):**  
Resume and cover letter writing guidelines matched per role.

**AI Assist panel (web):**  
On the `/master-data` page, each tab (resume, bio, stories) has an "Improve with AI" panel. For stories, a "New story from description" workflow generates a fully structured story draft with frontmatter. The bio and resume tabs support instruction-driven revision.

### 3.8 Configuration & LLM Routing

**Config editor (`/config`):**  
Raw `config.yaml` editor with syntax highlighting. Also shows provider connectivity test results (real small LLM call per provider to verify key validity and model accessibility, with latency shown).

**Workflow LLM router (`/workflows`):**  
Visual editor for per-task LLM routing. Each task (ranking, tailoring, tailoring_premium, cover_letter, critique, answer_questions, coach, interview, essay, content_studio) can independently specify primary provider, fallback chain, and per-provider model overrides. Unrouted tasks inherit the global chain. Writes through to `config.yaml` using ruamel.yaml to preserve comments.

**Supported LLM providers:**  
Claude (Anthropic), Gemini (Google), Ollama (local), NIM (NVIDIA), OpenRouter, DeepSeek, Mistral.

**Fallback chain:**  
On quota or any transient error, the pipeline automatically retries with the next provider in the configured chain — fully transparent to the user.

---

## 4. Onboarding

A first-run wizard at `/onboarding` gates the app for new installs. The `onboarding-gate.tsx` component redirects any page to `/onboarding` until setup is complete. Steps:

1. **Provider** — enter at least one LLM API key (or configure Ollama)
2. **Contact** — name, email, phone, LinkedIn URL (populates document headers)
3. **Resume** — upload PDF/DOCX/TXT or paste text; AI extracts structured YAML
4. **AI Interview** — conversational interview to generate bio and narrative stories
5. **Search preferences** — keywords, location, minimum score threshold, max jobs per day

The `GET /api/onboarding/status` endpoint tracks which steps are complete and whether `can_run` is satisfied. Config writes round-trip through ruamel.yaml so comments are preserved.

---

## 5. Data Model

### 5.1 Runs

| Field | Type | Notes |
|---|---|---|
| id | int (PK) | |
| started_at | datetime | |
| finished_at | datetime? | |
| status | enum | queued, running, done, error, cancelled |
| dry_run | bool | |
| no_pdf | bool | |
| no_cache | bool | |
| jobs_found | int | |
| applications_created | int | |
| day_root | str? | path to output folder for the day |
| log_path | str? | path to log file |
| error | str? | error message if failed |

### 5.2 Applications

| Field | Type | Notes |
|---|---|---|
| id | int (PK) | |
| run_id | int? (FK) | null for manually created |
| company | str | |
| title | str | |
| location | str | |
| url | str | original job posting URL |
| source | str | scraper that found it |
| match_score | int | 0–100 LLM fit score |
| match_reason | str | LLM rationale |
| description | str | job description text (used by Coach) |
| folder_path | str | absolute path on disk |
| folder_rel | str | relative path e.g. `2026-05-10/Company_Role` |
| resume_file | str | filename of generated resume |
| cover_file | str | filename of generated cover letter |
| answers_file | str | filename of supplemental answers |
| status | enum | generated, applied, interviewing, rejected, offer, archived |
| notes | str | user free-text notes |
| tags | str | comma-separated; exposed as list by API |
| applied_at | datetime? | |
| deadline | datetime? | |
| created_at | datetime | |

### 5.3 Ranked Jobs (Full Pool)

Stores the complete scored pool per run, including jobs that were not selected for generation. Enables post-run triage.

| Field | Type | Notes |
|---|---|---|
| id | int (PK) | |
| run_id | int (FK) | |
| company, title, location, url, source | str | |
| description | str | job description (for on-demand generation) |
| remote | bool | |
| match_score | int | |
| match_reason | str | |
| selected | bool | was it auto-picked for this run? |
| application_id | int? (FK) | set when generated/rescued |

### 5.4 Chat Sessions and Messages

| Field | Type | Notes |
|---|---|---|
| ChatSession.id | int (PK) | |
| ChatSession.title | str | auto-generated from first exchange |
| ChatSession.mode | str | "chat" or "interview" |
| ChatSession.application_id | int? (FK) | optional grounding |
| ChatMessage.role | str | "user" or "assistant" |
| ChatMessage.content | str | |

### 5.5 Saved Answers

| Field | Type | Notes |
|---|---|---|
| id | int (PK) | |
| title | str | |
| prompt | str | the question that was answered |
| content | str | the answer text |
| tags | str | comma-separated |
| application_id | int? (FK) | optional link to application |

---

## 6. Technical Architecture

### 6.1 Backend (`server/`)

FastAPI server. Runs on port 8000 by default.

**Routers:**

| Router | Prefix | Responsibility |
|---|---|---|
| `runs.py` | `/api/runs` | Start run, list/get runs, stop, SSE stream, log file, ranked pool CRUD |
| `applications.py` | `/api/applications` | CRUD, status/tags, deadline, bulk update, CSV export |
| `single_job.py` | `/api/single-job` | URL extract + single-job generation; shared `start_generation()` used by ranked rescue |
| `ranked.py` | `/api/ranked` | Ranked pool triage; rescue (generate) a non-selected job |
| `tweak.py` | `/api/applications/{id}` | Resume tweak, resume versions, cover letter GET/PUT |
| `config_api.py` | `/api/config` | Read/write config.yaml and master-data text files |
| `ops.py` | `/api/providers`, `/api/compare`, `/api/llm-config` | Provider tests, two-run diff, per-workflow LLM routing |
| `chat.py` | `/api/chat` | Coach sessions, messages, kickoff, essay drafter, answer bank |
| `studio.py` | `/api/master-data` | AI-assisted story generation and content revision |
| `stats.py` | `/api/stats` | Aggregated analytics |
| `onboarding.py` | `/api/onboarding` | First-run setup status and structured config writers |

**Database:** SQLite via SQLModel at `data/app.db`. `_migrate()` adds new columns to existing tables (SQLModel's `create_all` only creates missing tables).

**Real-time events:** In-process pub/sub via `server/events.py`. The pipeline worker thread calls `bus.publish_threadsafe(run_id, event)`, which fan-outs to all SSE subscribers. The `EventBus` stores a bounded history (2000 events per run) for late-joining clients. The `GET /api/runs/{id}/stream` endpoint delivers events as Server-Sent Events.

**Static file serving:** The `output/` folder is mounted at `/files/*`, so generated documents are accessible directly by relative path.

### 6.2 Pipeline Engine (`src/`)

| Module | Responsibility |
|---|---|
| `pipeline.py` | `run_pipeline()` — the importable orchestrator; all stages, stop-check polling, event emission |
| `main.py` | CLI entry point; `setup_logging()`, `process_job()`, `fetch_all()` |
| `tailor.py` | LLM calls: `rank_jobs()`, `tailor_resume()`, `write_cover_letter()`, `answer_questions()` |
| `resume_builder.py` | Renders one-page ATS-safe `.docx` from tailored JSON. Line-count estimator with iterative overflow recovery. |
| `profile.py` | `derive_profile(master)` — derives candidate identity (titles, seniority, education proximity) from resume.yaml for use in prompts and guards |
| `tailor_graph.py` | Full tailoring pipeline with quality stages: tailor → audit → keyword_fix? → critique → revise? → line_fitter → relinefit_rescue? |
| `providers/` | LLM abstraction layer. `factory.py` exposes `get_provider_chain()`, `get_task_chains()`, `try_chain()`. Implementations for Claude, Gemini, Ollama, NIM, OpenRouter, DeepSeek, Mistral. |
| `scrapers/` | One scraper per source (see §6.4). All return the unified `Job` dataclass. |
| `reference_loader.py` | Loads stories and example letters; `match_stories()` scores by tag/keyword overlap |
| `content_studio.py` | `generate_story()`, `tweak_content()`, `import_resume()` — LLM-assisted master-data authoring |
| `tweak.py` | Post-generation CLI and API resume tweaking with versioned output |
| `job_extractor.py` | Scrapes and LLM-extracts a job posting from a URL |

### 6.3 Frontend (`web/`)

Next.js 16 (App Router, Turbopack) + Tailwind v4 + shadcn/ui + MagicUI. Dark mode default; unified indigo accent with CSS token-based theming.

**Navigation groups:**

| Group | Pages |
|---|---|
| Workspace | `/` dashboard, `/run` live pipeline, `/applications` table+kanban, `/applications/[id]` detail, `/single` 3-step wizard |
| Prepwork | `/coach` chat, `/interview` mock interview, `/essay` essay drafter |
| Insights | `/runs` history, `/runs/[id]` detail+triage, `/runs/compare` diff, `/stats` charts |
| Setup | `/config` editor, `/workflows` LLM router, `/master-data` resume/bio/stories |

**Key libraries:**
- TanStack Query v5 — server state, adaptive polling
- Zustand — ephemeral UI state (active run ID, command palette, sidebar collapsed)
- motion v12 — BlurFade, MagicCard, DotPattern animations
- Recharts — stats charts
- next-themes — dark/light mode
- react-markdown + remark-gfm — Coach message rendering

**Performance characteristics:**
- `staleTime: 30s`, `refetchOnMount: false` — revisiting a page within 30s serves from cache
- Adaptive polling: `/api/runs` polled at 4s while a run is active, 20s at idle; page-level queries poll only while a run is active, otherwise `false`
- Single shared `useLatestRuns()` hook feeds both the global `RunStatusPill` and `RunActivityWatcher` — one network request per interval, not two

**Sidebar:** Collapsible to icon-only mode via header button or Cmd+B. Choice is persisted to localStorage.

**Cmd+K command palette:** Global search/navigation.

### 6.4 Job Sources

| Source | Type | Notes |
|---|---|---|
| Simplify (GitHub) | Scraped list | ~1100 SWE internship/new-grad roles maintained on GitHub |
| Greenhouse | Direct API | 20+ hardcoded company slugs; configurable in `config.yaml` |
| JSearch (RapidAPI) | API | General job search |
| Adzuna | API | Job board aggregator |
| Remotive | API | Remote-first roles |
| Lever | API | ATS direct |
| TheMuse | API | Curated company culture-forward postings |

Each scraper returns the unified `Job` dataclass: `source`, `company`, `title`, `location`, `url`, `description`, `remote`, `additional_questions`, `specific_instructions`.

---

## 7. Configuration Reference

All config lives in `config.yaml` (gitignored; seeded from `config.example.yaml` on first run).

| Section | Key fields |
|---|---|
| `user` | `full_name`, `email`, `phone`, `linkedin`, `github`, `website` |
| `search` | `keywords` (list), `location`, `min_match_score` (default 55), `max_jobs_per_day` (default 50) |
| `sources` | `enabled` per scraper; `greenhouse_slugs` list |
| `llm` | `primary`, `fallbacks`, per-provider `api_key`+`model`, `tasks.<task>` overrides, `critique_cover_letters`, `critique_top_n`, `tailoring_premium_top_n` |
| `output` | `root` (folder), `font`, `base_font_size`, margins, `produce_pdf` |

LLM task names: `ranking`, `tailoring`, `tailoring_premium`, `cover_letter`, `critique`, `answer_questions`, `coach`, `interview`, `essay`, `content_studio`.

API keys can also be set via env vars: `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`, `MISTRAL_API_KEY`.

---

## 8. Scheduling

| Platform | Method |
|---|---|
| Linux/macOS | `bash scripts/setup_cron.sh` |
| Windows | `.\scripts\setup_task_scheduler.ps1 -Time "08:00"` |

The scheduled task calls `python -m src.main` (CLI mode), which bypasses the web server entirely and writes output directly to disk.

---

## 9. Output Artifacts

For each application, the following are written to `output/YYYY-MM-DD/<Company_Role>/`:

| File | Description |
|---|---|
| `resume.docx` | One-page tailored resume (ATS-safe, Times New Roman 10pt) |
| `resume.pdf` | PDF version (requires Word or LibreOffice) |
| `resume.json` | Structured JSON used to build the docx; retained for tweaking |
| `cover_letter.docx` | Tailored cover letter |
| `cover_letter.pdf` | PDF version |
| `answers.md` | Answers to supplemental application questions |
| `job.json` | Snapshot of the job posting data |

After tweaks, versioned files appear: `resume.v2.docx`, `resume.v2.pdf`, etc.

The day's Excel tracker is written to `output/YYYY-MM-DD/apps_YYYY-MM-DD.xlsx`.

---

## 10. Resume Tailoring Constraints

The tailoring engine enforces strict one-page limits. Key rules:

- **Preserve full-time roles.** For candidates with professional experience, full-time employment history is never dropped.
- **No em dashes.** Stripped for ATS compatibility (uses commas or semicolons).
- **Profile-driven identity.** The summary opening must use the candidate's real titles (derived from `src/profile.py`), never the JD's title. Fabrication of identity is explicitly prohibited in prompts.
- **Line-fill rule.** Bullets must be either a clean single line (≥88% of the line width) or a full two-line wrap. The orphan zone (a very short second line) is forbidden. A deterministic line-count estimator runs after tailoring; if overflow or orphan-wrap violations are detected, a two-phase LLM rescue (compress then extend) is attempted.
- **Font-aware bands.** Line width bands are derived from `output.base_font_size` (default 10pt: single line 79–130 chars, target fill ≥116 chars, double 205–258 chars).

---

## 11. Known Constraints and Limitations

- **Single-tenant.** One candidate profile per install. Multi-user is not supported.
- **PDF conversion requires Word or LibreOffice.** On machines with neither, use `--no-pdf`.
- **LinkedIn scraping blocked by design.** LinkedIn aggressively blocks automated browsers. Job postings from LinkedIn must be pasted manually via the single-job wizard.
- **No real-time token usage tracking.** The provider abstraction layer does not expose token counts, so there is no per-run cost estimate in the UI. Cost reference: Claude Haiku ~$0.10–0.30/run (30 jobs); Gemini Flash / Ollama effectively free.
- **Coach is send-and-wait, not streaming.** The Prepwork chat endpoints return the complete assistant response synchronously; there is no streaming UI for Coach replies.
- **DeepSeek API limitation.** DeepSeek's API does not support `json_schema` response format (returns 400). Only `json_object` is used with schema embedded in the prompt. Legacy names `deepseek-chat`/`deepseek-reasoner` retired 2026-07-24; the current models are `deepseek-v4-flash` (default for all tasks) and `deepseek-v4-pro` (reserved for `tailoring_premium`, ~3x pricier). Both are dual-mode reasoning models that emit chain-of-thought to a separate `reasoning_content` field by default — disable per-task via `llm.tasks.<task>.thinking: false` for bounded structured tasks (ranking, critique) where CoT only adds latency.

---

## 12. Development Setup

```bash
# Python backend
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt

# Web frontend
cd web && npm install

# Start both (Windows)
.\scripts\dev.ps1               # API :8000, web :3000

# Or individually
python -m uvicorn server.app:app --reload --port 8000
cd web && npm run dev
```

**Dry run (no LLM tailoring cost):**
```bash
python -m src.main --dry-run
```

**Tweak a generated resume:**
```bash
python -m src.tweak output/2026-04-24/Company_Role/resume.docx "Emphasize LangGraph work"
```
