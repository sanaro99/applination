# Applination

Applying for jobs is mostly repetitive work. You find a posting, read it, decide whether it is worth your time, rewrite your resume so it echoes the language in the job description, write a cover letter that sounds like you actually want *this* job rather than any job, and then write the whole thing down somewhere so you remember who you are waiting to hear back from.

**Applination does that loop for you, every day, while you do something else.**

You tell it about yourself once. After that it goes looking for jobs each morning, decides which ones genuinely suit you, and writes a resume and cover letter aimed at each one. What you get back is a short list of good matches with the paperwork already done — so the only thing left is to read it over and hit send.

**Live app:** https://applination.sanchitarora.me · **Source:** https://github.com/sanaro99/applination

---

## Try it without signing up

There is a shared demo account — a made-up candidate named **John Doe** — already filled with jobs, applications, finished resumes and cover letters. Click **Try the demo** next to the login form and you are straight in, with everything working and nothing to set up.

A guided walkthrough starts automatically the first time and points out what each screen is for. You can skip it, and you can replay it later from the account menu.

Two things to know: the demo's AI answers are pre-recorded rather than live, and the account resets every night. Everything else behaves exactly like the real thing.

---

## How it works

1. **You introduce yourself, once.** Upload your existing resume and Applination reads it into a structured profile. A short conversation with the AI fills in the gaps and captures a few stories about your work — the kind of thing you would tell an interviewer.
2. **It goes looking for jobs.** Every day it checks seven public job sources and collects everything that matches the kinds of roles you asked for.
3. **It decides what is actually worth your time.** Each posting is read against your background and given a score out of 100. Anything below your chosen cutoff is dropped, so you are not handed 200 links to sift through.
4. **It writes the paperwork.** For each of the best matches it rewrites your resume around that specific job and drafts a cover letter in your own voice, drawing on the stories you gave it. Both come out as Word and PDF files, kept to one page.
5. **It keeps track.** Everything lands in a tracker you can sort, tag, and move through stages — applied, interviewing, offer, rejected — plus a dated spreadsheet if you prefer one.

---

## What you get

**A shortlist instead of a firehose.** The point of the score is subtraction. You see the handful of jobs worth applying to, and you can look at the full ranked list to check its reasoning or rescue something it passed over.

**Documents written for one job, not one template.** The resume is genuinely rebuilt for each posting — bullets reworded and reordered around what that employer asked for — rather than a stock document with the company name swapped in. Everything stays on one page and in a plain format that applicant tracking systems (the software that filters resumes before a person reads them) can actually parse. You can then tweak any resume by just telling it what to change, and compare versions side by side.

**A tracker that updates itself.** If you connect your Gmail, Applination reads replies from companies you applied to and moves each application along on its own — interview scheduled, rejected, offer. Deadlines and interviews can feed straight into your calendar app, and it can email you a daily summary of what needs attention. The email sorting happens inside your own browser, so the contents of your inbox never get sent anywhere.

**Interview prep that already knows your background.** A coach you can chat with, a mock interview that asks one question at a time and critiques your answers, and a drafter for those long "why do you want to work here" essays. All three read your actual resume and stories, so the answers are about you. Good answers can be saved and reused.

**One job at a time, when you want that instead.** Found a posting yourself? Paste the link, and it will pull out the details and write the documents for that single job.

**Your own AI, your own bill.** Applination does not resell anyone's AI. You bring a key from whichever provider you prefer — Anthropic, Google, DeepSeek, Mistral, OpenRouter, Nvidia — or run a model on your own machine with Ollama and pay nothing at all. Your key is encrypted before it is stored, and you can point different jobs at different models: something cheap and fast for scoring hundreds of postings, something stronger for writing the documents you will actually send.

**Your data stays yours.** Every account is separate, with its own profile, settings and generated documents. Nothing personal is ever committed to this repository.

---

## Feature overview

| Area | What you get |
|---|---|
| **Daily run** | Full fetch → score → write loop, streamed live; dry-run mode previews the scoring without spending money on documents |
| **Application tracker** | Table and Kanban views; status, notes, deadlines, tags, bulk edits, CSV export |
| **Application detail** | PDF preview, resume tweaking by instruction (versioned), cover-letter editing, side-by-side resume diff |
| **Single-job wizard** | Paste a URL or description → fields extracted → review → documents, in three steps |
| **Ranked triage** | The full scored list for every run; rescue anything that was not auto-selected, dismiss anything you never want to see again |
| **Prepwork** | AI coach, mock interview, essay drafter, and a reusable answer bank — all grounded in your profile |
| **Insights** | Run history, log viewer, run-to-run comparison, and charts for scores, sources and outcomes |
| **Close the loop** | Gmail sync that advances application status from real replies, a calendar feed, and a daily email digest |
| **Setup** | Config editor with live provider testing, a visual editor for routing each task to a different model, and an AI-assisted editor for your resume and stories |
| **Guided tour** | A walkthrough of the whole app that starts on first login and can be replayed any time |

---

# Technical details

Everything above is the product. The rest of this document is how to run it.

## Architecture at a glance

- **`src/`** — the engine: job sources, scoring, resume and cover-letter generation, document rendering. Knows nothing about the web app and can be driven from the command line.
- **`server/`** — a FastAPI layer in front of `src/`: accounts, per-user data isolation, encrypted key storage, and the REST + server-sent-events API.
- **`web/`** — a Next.js 16 front end (App Router, Tailwind v4, shadcn/ui).
- **Postgres** — accounts, sessions, runs, applications, the ranked pool and Prepwork history. Schema is owned by Alembic. Generated documents live on disk, not in the database.

Applination is **multi-user**. Anyone can sign up; each account brings its own API keys and keeps its own config, profile and documents under `data/users/<id>/`. That whole directory is gitignored — this repository is public.

## Prerequisites

- **Python 3.11+**
- **Node.js 20+** and npm
- **PostgreSQL 18** — `scripts/dev.ps1` starts one in Docker automatically if nothing is listening on port 5432; otherwise point `DATABASE_URL` at your own
- At least one LLM provider key, or a running Ollama instance (free)
- **PDF conversion** (optional): Microsoft Word (Windows/macOS) or LibreOffice (`soffice` on PATH, Linux). Use `--no-pdf` if you have neither.

## Getting started

### 1. Clone and install

```bash
git clone https://github.com/sanaro99/applination.git
cd applination

python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt

cd web
npm install
cd ..
```

### 2. Set the encryption key

API keys and Gmail tokens are encrypted at rest with a Fernet key the server holds:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Put the result in `APPLINATION_SECRET_KEY` in your environment. Without it the app runs, but it cannot store API keys.

### 3. Start the development servers

```powershell
.\scripts\dev.ps1
```

This brings up Postgres if needed, applies migrations, then starts the FastAPI backend on **http://127.0.0.1:8000** and the Next.js front end on **http://127.0.0.1:3000**.

To run them separately:

```bash
python -m uvicorn server.app:app --reload --reload-dir server --reload-dir src --port 8000
cd web && npm run dev
```

### 4. Optional: the in-browser email classifier

Inbox sync sorts emails using a small model that runs inside your browser. Download it once per clone:

```bash
python scripts/fetch_webllm_model.py
```

This fetches roughly 700MB into `web/public/models/` (gitignored) so the browser does not have to reach huggingface.co, which some networks block. Skip it if you are not using inbox sync.

### 5. Sign up and onboard

Open **http://localhost:3000**, create an account, and the setup wizard walks you through:

| Step | What happens |
|---|---|
| Provider | Your API key is validated with a real test call, then encrypted and stored |
| Contact | Name, email, phone and LinkedIn, used in the documents it renders |
| Resume | PDF/DOCX/text is extracted into `master_data/resume.yaml` |
| Interview | A short AI conversation fills experience gaps and drafts your bio and first stories |
| Search prefs | Job titles, locations, minimum score, and a cap on documents per run |

### 6. Dry run, then a full run

A dry run fetches and scores jobs without generating any documents — much cheaper, and a good way to sanity-check your search settings.

```bash
python -m src.main --dry-run    # or: Start run → Dry run in the dashboard
python -m src.main              # the full loop
```

## CLI reference

The CLI is owner-operated and reads the same per-user data and decrypted keys the server does.

```bash
python -m src.main --dry-run                  # fetch + score only
python -m src.main                            # full run
python -m src.main --no-pdf                   # .docx only, no PDF conversion
python -m src.main --user someone@example.com # run as a specific account

# Tweak a generated resume
python -m src.tweak data/users/1/output/2026-04-24/Company_Role/resume.docx "Emphasize LangGraph work"
python -m src.tweak resume.docx "more ML focus" --provider gemini
python -m src.tweak resume.docx --interactive
```

## Output artifacts

Each run creates `data/users/<id>/output/YYYY-MM-DD/<Company_Role>/`:

| File | Description |
|---|---|
| `resume.docx` / `resume.pdf` | Tailored one-page resume |
| `resume.json` | Structured JSON — the input for `src/tweak.py` |
| `cover_letter.docx` / `cover_letter.pdf` | Personalised cover letter |
| `job.json` | Snapshot of the posting (company, title, description, URL) |
| `answers.md` | Drafted answers to screening questions, when the posting has any |

Plus `apps_YYYY-MM-DD.xlsx` in the dated folder — the daily tracker.

Documents are served through `GET /api/files/{rel_path}`, resolved against the calling account's own output directory. There is no static file mount.

## Job sources

Seven sources, each toggled in `sources:`:

| Source | Key required | Notes |
|---|---|---|
| **Remotive** | none | Remote roles only |
| **The Muse** | none | Good variety |
| **Greenhouse** | none | 140 known company boards built in; add your own slugs |
| **Lever** | none | Company boards you list |
| **Simplify (GitHub)** | none | The Pitt CSC internship list, ~1100 roles |
| **Adzuna** | free registration | https://developer.adzuna.com |
| **JSearch** | RapidAPI | LinkedIn + Indeed coverage; free tier is 200 requests/month |

LinkedIn is not scraped directly — it is rate-limited and requires a login.

## LLM providers

Seven providers, any of which can be primary or fallback. Keys are entered in the app and stored encrypted per account.

| Provider | Notes |
|---|---|
| **Claude** (Anthropic) | Haiku ~$0.10–0.30/run; Sonnet ~$1–3/run |
| **Gemini** (Google) | Flash is effectively free |
| **DeepSeek** | Cheapest cloud path; `deepseek-v4-flash` standard, `deepseek-v4-pro` premium |
| **Mistral** | Solid mid-tier |
| **OpenRouter** | Many models behind one key |
| **Ollama** (local) | Free; requires `ollama serve` |
| **Nvidia NIM** | Cloud or self-hosted inference |

Each workflow — scoring, tailoring, cover letters, critique, coach, interview, essay — can be routed to a different provider and model from the **Workflows** page.

> **On environment variables:** `ANTHROPIC_API_KEY` and friends are **ignored** unless `ALLOW_ENV_API_KEYS` is set. They belong to the server process rather than to any account, so on a multi-user install the fallback would let a user with no key of their own quietly spend the operator's. Only enable it for a single-user deployment.

## Your profile data

Per-account, under `data/users/<id>/master_data/`:

| File | Purpose |
|---|---|
| `resume.yaml` | Your full master resume — the source of truth for all content |
| `bio.md` | Voice and tone reference, injected into cover-letter prompts |
| `stories/*.md` | Narrative stories with YAML frontmatter, matched to jobs automatically |
| `cover_letters/examples/` | Past letters as `.md`, used as style anchors |

Stories carry `tags`, `role_fit`, `company_fit` and `one_liner` in their frontmatter; the cover-letter builder picks the one or two most relevant per job by tag overlap and keyword matching. You can write them by hand or generate them from a description on the **Master Data** page.

Writing guidelines (`master_data/guidelines/*.md`) and document templates are shared by every account and live in the repository.

## Configuration reference

Per-account, at `data/users/<id>/config.yaml`. Editable from the **Config** page; a new account is seeded from `config.example.yaml`.

```yaml
user:
  name: "..."
  email: "..."
  phone: "..."
  linkedin: "..."

search:
  keywords: [software engineer intern, ...]
  locations: [Remote, New York, ...]
  min_match_score: 55       # 0-100; anything below this is dropped
  max_jobs_per_day: 50      # cap on documents generated per run

llm:
  primary: "claude"
  fallbacks: ["gemini"]
  claude:
    model: "claude-haiku-4-5-20251001"
  tasks:                    # per-workflow overrides
    tailoring_premium:
      primary: "deepseek"
    coach:
      primary: "gemini"

output:
  root: "output"
  produce_pdf: true
  base_font_size: 10

inbox:                      # Gmail sync (optional, off by default)
  enabled: false
  client_id: ""             # OAuth client from Google Cloud Console
  client_secret: ""
  redirect_uri: "http://127.0.0.1:8000/api/inbox/oauth/callback"
  scan_days: 30
  min_confidence: 0.6       # only change status when this confident
  auto_update_status: true

reminders:
  digest_enabled: false
  deadline_window_days: 3
  follow_up_days: 7
```

API keys are deliberately absent from this file. They are diverted into an encrypted database table on write and merged back in on read, so nothing downstream knows the difference.

## Daily scheduling

```bash
bash scripts/setup_cron.sh              # macOS / Linux
```
```powershell
.\scripts\setup_task_scheduler.ps1      # Windows; -Time "HH:mm" to override
```

## Known constraints

- **PDF conversion** needs MS Word (Windows/macOS) or LibreOffice (Linux); use `--no-pdf` otherwise.
- **LinkedIn** is not scraped — rate-limited and login-walled.
- **Coach replies do not stream.** They are send-and-wait, because no provider in the abstraction layer streams yet.
- **No token/cost tracking.** The provider layer does not expose usage, so "insights" cover timing, throughput and scores rather than spend.
- **No password reset by email.** Use `scripts/set_password.py` from the console.
- **Greenhouse slugs** in `config.example.yaml` are illustrative — replace them with companies you care about.
