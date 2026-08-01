# Applination

AI-assisted job application pipeline (internships, new-grad, and full-time). Every day it fetches fresh job postings, uses an LLM to rank them against your background (0–100 fit score), tailors your resume, and writes a cover letter for each top match — all from a web dashboard or the CLI.

**GitHub:** https://github.com/sanaro99/applination

---

## What it does

1. Fetches fresh job postings from 8 public APIs / aggregators
2. Uses an LLM to score each job against your background (0–100 fit)
3. Tailors your resume per job and writes a personalised cover letter
4. Enforces a one-page ATS-safe `.docx` / `.pdf` output
5. Produces a daily Excel tracker with status dropdowns and hyperlinks

---

## Feature overview

| Area | What you get |
|---|---|
| **Daily pipeline run** | Full fetch → rank → tailor loop; dry-run mode for free preview |
| **Web dashboard** | Live SSE progress stream, job cards with scores, cancel mid-run |
| **Application tracker** | Table + Kanban view; status, notes, deadline, tags, bulk edits, CSV export |
| **Application detail** | PDF preview, inline resume tweak (versioned), cover-letter editor, resume diff |
| **Single-job wizard** | Paste a URL or JD → AI extracts fields → review → generate tailored docs in 3 steps |
| **Ranked triage** | Full scored pool per run; rescue any non-auto-selected job on demand |
| **Prepwork (Coach)** | Chat with an AI coach grounded on your resume and stories; mock interview mode; essay drafter; reusable answer bank |
| **Insights** | Run history, log viewer, run compare (diff two runs), stats charts (scores, sources, status) |
| **Setup** | In-app `config.yaml` editor with live provider test, visual per-workflow LLM routing editor, master-data editor with AI-assist |
| **Close the loop** | Gmail inbox sync (IMAP) classifies recruiter emails → auto-updates application status; iCal feed for deadlines + interviews; daily email digest |

---

## Prerequisites

- **Python 3.11+**
- **Node.js 20+** and npm
- At least one LLM provider key (or a running Ollama instance — free)
- **PDF conversion** (optional): Microsoft Word (Windows/macOS) or LibreOffice (`soffice` on PATH, Linux). Skip with `--no-pdf` if neither is available.

---

## Getting started (recommended path)

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

### 2. Start the development servers

```powershell
.\scripts\dev.ps1
```

This starts:
- FastAPI backend on **http://127.0.0.1:8000**
- Next.js frontend on **http://127.0.0.1:3000**

Open **http://localhost:3000** in your browser.

### 3. Complete onboarding

On first launch you'll be redirected to the onboarding wizard:

1. **Provider** — enter your LLM API key (Claude, Gemini, DeepSeek, etc.) or choose Ollama
2. **Contact** — name, email, phone, LinkedIn URL (used in rendered documents)
3. **Resume** — upload a PDF/DOCX or paste text; AI extracts it into structured master data
4. **Interview** — a short AI conversation fills experience gaps and drafts your story bank
5. **Search prefs** — job titles, locations, minimum match score, max jobs per day

Your data stays local in gitignored files (`config.yaml`, `master_data/`).

### 4. Run dry run (free — no tailoring LLM calls)

Click **Start run → Dry run** in the dashboard, or:

```bash
python -m src.main --dry-run
```

Fetches and ranks jobs; writes `output/YYYY-MM-DD/ranked_jobs.json`. No resume generation.

### 5. Full run

Click **Start run** in the dashboard, or:

```bash
python -m src.main
```

---

## CLI quick reference

```bash
# Dry run
python -m src.main --dry-run

# Full run
python -m src.main

# Skip PDF (produce .docx only)
python -m src.main --no-pdf

# Tweak a generated resume
python -m src.tweak output/2026-04-24/Company_Role/resume.docx "Emphasize LangGraph work"
python -m src.tweak resume.docx "more ML focus" --provider gemini
python -m src.tweak resume.docx --interactive
```

---

## Output artifacts

Each run creates `output/YYYY-MM-DD/<Company_Role>/` containing:

| File | Description |
|---|---|
| `resume.docx` / `resume.pdf` | Tailored one-page resume |
| `resume.json` | Structured JSON (input for `tweak.py`) |
| `cover_letter.docx` / `cover_letter.pdf` | Personalised cover letter |
| `job.json` | JD snapshot (company, title, description, URL) |
| `answers.md` | AI-drafted screening question answers (if any) |

Plus `output/YYYY-MM-DD/apps_YYYY-MM-DD.xlsx` — daily Excel tracker.

---

## Daily scheduling

### macOS / Linux (cron)

```bash
bash scripts/setup_cron.sh
```

### Windows (Task Scheduler)

```powershell
.\scripts\setup_task_scheduler.ps1 -Time "08:00"
```

---

## LLM providers

All 7 providers are supported; any can be primary or fallback. Configure in `config.yaml` or via the **Setup → Workflows** page.

| Provider | Key env var | Notes |
|---|---|---|
| **Claude** (Anthropic) | `ANTHROPIC_API_KEY` | Haiku ~$0.10–0.30/run; Sonnet ~$1–3/run |
| **Gemini** (Google) | `GOOGLE_API_KEY` | Flash is effectively free |
| **DeepSeek** | `DEEPSEEK_API_KEY` | `deepseek-v4-flash` for standard; `deepseek-v4-pro` for premium tier |
| **Mistral** | `MISTRAL_API_KEY` | Good mid-tier option |
| **OpenRouter** | `OPENROUTER_API_KEY` | Access to many models via one key |
| **Ollama** (local) | none | Fully free; requires `ollama serve` |
| **Nvidia NIM** | `NIM_API_KEY` | Self-hosted or cloud inference |

Per-workflow routing (ranking, tailoring, cover letter, Coach, etc.) is configurable independently via the **Workflows** page.

---

## Master data

| File | Purpose |
|---|---|
| `master_data/resume.yaml` | Full master resume — source of truth for all content |
| `master_data/bio.md` | Voice/tone reference injected into cover-letter prompts |
| `master_data/stories/*.md` | Narrative stories with YAML frontmatter; auto-matched to jobs |
| `master_data/cover_letters/examples/` | Past letters as `.md` files; used as style anchors |
| `master_data/guidelines/*.md` | Resume/cover-letter writing rules matched per role |

Stories use YAML frontmatter (`tags`, `role_fit`, `company_fit`, `one_liner`). The cover letter builder picks the 1–2 most relevant stories per job by tag overlap + keyword matching. Stories can be generated from the **Master Data** page using AI.

---

## Onboarding flow detail

| Step | What happens |
|---|---|
| Provider | Validates the key with a real test call; saved to `config.yaml` |
| Contact | Name/email/phone/LinkedIn written to `config.yaml user:` section |
| Resume import | PDF/DOCX/text → `src/content_studio.import_resume()` → `master_data/resume.yaml` |
| AI interview | Multi-turn conversation extracts experience gaps, drafts `bio.md` + initial stories |
| Search prefs | Keywords, locations, `min_match_score`, `max_jobs_per_day` saved to `config.yaml search:` |

After onboarding, `GET /api/onboarding/status` returns `can_run: true` and the dashboard unlocks.

---

## Configuration reference

Key sections in `config.yaml`:

```yaml
user:
  name: "..."
  email: "..."
  phone: "..."
  linkedin: "..."

search:
  keywords: [software engineer intern, ...]
  locations: [Remote, New York, ...]
  min_match_score: 55       # 0-100 threshold; jobs below this are skipped
  max_jobs_per_day: 50      # cap on auto-tailored applications per run

llm:
  primary: "claude"
  fallbacks: ["gemini"]
  claude:
    api_key: ""
    model: "claude-haiku-4-5-20251001"
  # Per-workflow overrides:
  tasks:
    tailoring_premium:
      primary: "deepseek"
    coach:
      primary: "gemini"

output:
  root: "output"
  produce_pdf: true
  base_font_size: 10

inbox:                        # Close-the-loop inbox sync (optional)
  email: ""
  app_password: ""            # Gmail App Password (not your login password)
  auto_update_status: true
  min_confidence: 0.7

reminders:
  digest_enabled: false
  deadline_window_days: 3
  follow_up_days: 7
```

---

## Known constraints

- **Single-tenant**: one profile per install (but any person's profile — not hardcoded to any one user)
- **PDF conversion**: requires MS Word (Windows/macOS) or LibreOffice (Linux); use `--no-pdf` otherwise
- **LinkedIn scraping**: not supported (rate-limited / requires login)
- **No streaming in Coach**: responses are send-and-wait; streaming not yet implemented
- **Greenhouse slugs**: the default list in `config.example.yaml` is illustrative — replace with companies you want to track
