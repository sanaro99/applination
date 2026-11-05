# Applination technical guide

This guide covers running and developing Applination. For the product walkthrough and screenshots, see the [main README](../README.md).

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
- At least one LLM provider key, or Ollama plus the local Applination worker
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

To run them separately, start Postgres and set `DATABASE_URL` to its connection string if you are not using the local default. Apply the schema before starting the API:

```bash
python -m alembic upgrade head
python -m uvicorn server.app:app --reload --reload-dir server --reload-dir src --port 8000
```

In a second terminal:

```bash
cd web
npm run dev
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

Eight sources, each toggled in `sources:`:

| Source | Key required | Notes |
|---|---|---|
| **Remotive** | none | Remote roles only |
| **The Muse** | none | Good variety |
| **Greenhouse** | none | Built-in company boards; add your own slugs |
| **Lever** | none | Company boards you list |
| **Simplify (GitHub)** | none | SimplifyJobs / Pitt CSC internship list |
| **Himalayas** | none | Remote roles through its public search API |
| **Adzuna** | registration | [Developer portal](https://developer.adzuna.com) |
| **JSearch** | RapidAPI | Job search API; access and limits depend on your plan |

LinkedIn is not scraped directly — it is rate-limited and requires a login.

## LLM providers

Ten providers, any of which can be primary or fallback. Keys are entered in the app and stored encrypted per account. New configurations use DeepSeek V4.1 Flash for every workflow, with Groq, Gemini, and Cloudflare as ordered fallbacks.

| Provider | Notes |
|---|---|
| **OpenAI** | Native OpenAI API; also supported for eligible bulk batch runs |
| **Claude** (Anthropic) | Native Anthropic API; also supported for eligible bulk batch runs |
| **Gemini** (Google) | Native Google API; also supported for eligible bulk batch runs |
| **DeepSeek** | `deepseek-flash` standard, `deepseek-v4-pro` premium in the default config |
| **Groq** | Cloud inference; configured as a default fallback |
| **Cloudflare** | Workers AI; uses an account ID and API token |
| **Mistral** | Native Mistral API |
| **OpenRouter** | Many models behind one key |
| **Ollama** (local) | No AI provider key; requires Ollama and the local Applination worker |
| **Nvidia NIM** | Cloud or self-hosted inference |

Each workflow — scoring, tailoring, cover letters, critique, coach, interview, essay — can be routed to a different provider and model from the **Workflows** page.

Costs and model access depend on your provider account and selected model. Use the app's provider test to confirm access; a catalog listing alone does not establish that your key can use a model.

### Use your own Ollama with the hosted website and extension

1. Install [Ollama](https://ollama.com/download) on the computer where you will use Applination, and run `ollama pull llama3.2` (or install the model you select in Workflows).
2. On Applination's **Config** page, find **Ollama on your computer**, download `applination-ollama-worker.py`, and create a pairing code. It expires in five minutes and works once.
3. Install Python 3.10 or newer, run `python applination-ollama-worker.py`, and paste the code into its hidden terminal prompt. Enter the verification code shown in that terminal into Config and approve the matching worker. Unexpected workers should be disconnected. No prompts are released before approval.
4. Keep the worker running for website generation, extension autofill, and scheduled runs. Sessions expire after 12 hours or one hour offline; pair again afterward. The worker saves sessions with Windows DPAPI protection on Windows or private file permissions on other systems.
5. Choose Ollama during onboarding or in Workflows. Onboarding makes Ollama the provider for every workflow and removes cloud fallbacks. If you use Workflows instead, set each task you want to run locally to Ollama and remove its cloud fallbacks.

The official worker connects outward to Applination and calls Ollama only on this computer's loopback address, without using HTTP proxies for local prompts. You do not need to expose Ollama to the internet or configure browser CORS. Disconnect a worker in Config to revoke its session and cancel its leased requests; changing your password also revokes every worker on your account. Run with `--reset` to pair again. The worker excludes cloud models from the inventory and checks `/api/show` for remote aliases before sending any inference prompt.

The server treats workers as untrusted clients: credentials cannot access regular account APIs, tasks are scoped to the account and claiming worker, expired leases and replayed results are rejected, and requests and responses have size limits. Existing credentials from the old protocol are deliberately invalidated by the security migration. Download the updated worker and pair again after deploying this update.

Run only a trusted worker downloaded from your Applination installation. A modified script runs with your OS permissions and could forward prompts elsewhere or fabricate answers. The server cannot attest that a response actually came from local Ollama; credential scoping contains the account access it grants, and DPAPI does not protect against malware already running as your Windows user.

If an older worker fails with HTTP 403 and "blocked access based on your browser's signature," download the current worker from Config and restart it. The current worker identifies itself to Cloudflare's Browser Integrity Check with an Applination user agent.

For a self-hosted single-machine CLI setup, the existing direct Ollama provider still calls `http://localhost:11434`. A self-hosted API can explicitly set `llm.ollama.transport: direct` to use its own loopback Ollama. Hosted accounts use the local worker by default.

**Load available models** in Config works before you enter an AI provider key. Cloud providers use the public [Models.dev catalog](https://models.dev); **Load models for my key** optionally queries the provider with your entered or stored credentials. Public listings do not confirm account access, so test your selection after saving. Ollama lists the models reported by your online local worker. If an older worker asks you to update, download the current worker from Config and restart it. Workers using the old credential protocol must pair again after the security migration.

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
  full_name: "..."
  email: "..."
  phone: "..."
  linkedin: "..."

search:
  keywords: [software engineer intern, ...]
  job_type: internship
  remote_ok: true
  onsite_cities: [Remote, New York, ...]
  min_match_score: 55       # 0-100; anything below this is dropped
  max_jobs_per_day: 50      # cap on documents generated per run

llm:
  primary: "deepseek"
  fallbacks: ["groq", "gemini", "cloudflare"]
  deepseek:
    model: "deepseek-flash"
  tasks:                    # provider chain inherited; tune reasoning by task
    ranking:
      thinking: off
    tailoring:
      thinking: on

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

## Discounted bulk run implementation

The run page's **Lower cost** option uses native OpenAI, Claude, or Gemini batch APIs for supported models. Provider routes and keys are validated before submission. The choice applies to that run; single-job generation and interactive tools use their own workflow settings.

- `src/batch/` contains provider adapters, capabilities, stage requests, and workflow replay.
- `server/batch_runs.py` coordinates dependent rounds on the existing server scheduler.
- `server/batch_store.py` persists state, submission identities, leases, and ownership in Postgres and private user directories.
- `web/components/batch-run-options.tsx` and `batch-run-progress.tsx` expose mode selection, progress, and recovery actions.

Apply current migrations with `python -m alembic upgrade head` before starting the server. The coordinator resumes saved batches after a restart, but the server needs to remain available to poll and advance the run. No separate hosted worker or paid queue is required.

Each dependent round can take up to 24 hours, so a complete run may take longer. The app labels eligible token usage at the provider's batch discount and displays dollar estimates only for routes with known pricing. Estimates are planning allowances rather than measured usage or spending caps.

Failed items pause for user review instead of automatically falling back to standard-price calls. Users choose a discounted retry or confirm standard-price completion. When a submission was accepted but its response was lost, recovery can link a completed provider batch by ID; request identities must match before consuming results. Cancellation stops new submissions and abandons unresolved work locally, but the provider may still process and bill an accepted batch.

Batch data is account-scoped, and generated documents pass the existing generation and grounding validators before publication. See the [batch run design](superpowers/specs/2026-10-01-discounted-bulk-runs-design.md) for the state model and recovery design.

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
- **Cost estimates are not billing records.** Run-review estimates use configured models and planning allowances. Insights cover timing, throughput and scores; confirm actual charges with your provider.
- **No password reset by email.** Use `scripts/set_password.py` from the console.
- **Greenhouse slugs** in `config.example.yaml` are illustrative — replace them with companies you care about.
