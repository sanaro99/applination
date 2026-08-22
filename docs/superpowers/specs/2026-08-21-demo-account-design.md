# Demo account — design

**Issue:** [#38](https://github.com/sanaro99/applination/issues/38)
**Date:** 2026-08-21
**Status:** approved

## Problem

Applination cannot be shown to anyone. Every account is BYOK and every account's
data is personal and gitignored, so a prospective user reaching the signup page
sees a password field and nothing else. Screenshots go stale; a live account is
not shareable.

## Goal

A shared, committable demo account — persona **John Doe**, `demo@applination.app`
— that anyone can enter from a small link beside the login and signup forms, and
in which **every** flow works, including the AI ones.

## Decisions

These were settled during brainstorming; the alternatives are recorded so they
are not relitigated.

| Decision | Chosen | Rejected |
|---|---|---|
| Isolation | One shared account | Per-visitor throwaway accounts (needs a cloner and a reaper) |
| Write policy | Fully writable, restored nightly | Read-only (the app feels dead); re-seed on every login (two visitors fight) |
| AI calls | **Simulated**, same UX, with a nudge | Blocked with an error; operator's real key behind caps |
| Fixture | Text **and** generated documents | Text only; no documents at all |

The AI decision is the load-bearing one. A demo that errors on "start a run" or
"ask the coach" demonstrates nothing — the AI *is* the product. Simulating at the
provider layer keeps the user experience identical and confines the whole
pretence to one file.

## Architecture

### 1. `demo_data/` — the committed fixture

A new top-level directory. Nothing in `.gitignore` matches it, so no ignore-file
changes are needed (`/data/users/` stays ignored — the demo's *live* tree is
seeded there, never committed).

```
demo_data/
  config.yaml                      # llm.primary: demo; no api keys
  master_data/
    resume.yaml
    bio.md
    stories/*.md                   # 5
    cover_letters/examples/*.md    # 2
  output/<Company_Role>/
    resume.docx  resume.pdf
    cover_letter.docx  cover_letter.pdf
    job.json  resume.json
    resume.v2.docx  resume.v2.json # on one folder, so version-diff has content
  seed.json                        # DB fixture (see below)
  llm/*.json                       # canned DemoProvider responses
```

`seed.json` holds `Run`, `Application`, `RankedJob`, `ChatSession`,
`ChatMessage` and `SavedAnswer` rows. **Every timestamp is a relative offset**
(`{"days_ago": 3}`), rebased to *now* at seed time. Absolute dates would rot
visibly: deadlines go negative, the upcoming-interviews card empties, `/stats`
flatlines, and the demo starts advertising abandonment.

Output folders on disk are stored without a date component and are placed under
a rebased `YYYY-MM-DD/` directory by the seeder, so `folder_rel` in the DB and
the tree on disk agree.

### 2. Persona and public-repo hygiene

This repository is public, so the fixture is fictional by construction:

- The persona's **own employment and education history uses invented
  organisations**. A real company must not appear to have employed a person who
  does not exist.
- **Real companies appear only as public job postings** — which is what they
  are. This keeps the demo legible without asserting anything untrue.
- Contact details are reserved/example values (`demo@applination.app`,
  `555-0100`), never a real person's.

### 3. `server/demo.py` — the seeder

- `DEMO_EMAIL` module constant, overridable by the `DEMO_EMAIL` env var, and an
  `is_demo_user(user)` helper. Deliberately **not** a new `User.is_demo` column:
  a column costs an Alembic migration and a schema change to express a fact that
  is already a single known identity.
- `ensure_demo_user()` — creates the `User` row if absent, with a random
  unguessable password. Nobody ever logs in by password; the password exists so
  the row is not a credential-less special case.
- `seed_demo(reset=True)` — deletes the demo user's rows from every tenant
  table, wipes `data/users/<demo_id>/`, copies `demo_data/` in, and inserts the
  DB rows with dates rebased. **Idempotent**: safe to run on a live install, on
  a fresh clone, and from cron.
- Queries here run outside any request and against a known user id, so they
  carry `# noscope:` reasons for `tests/test_scope_lint.py`.
- `scripts/seed_demo.py [--reset]` is the CLI entry point.

### 4. `src/providers/demo_provider.py` — simulated AI

Registered in `factory.get_provider` under the name `demo`. The demo account's
`config.yaml` sets `llm.primary: demo` with no fallbacks, which means **no other
module in `src/` needs to know the demo exists** — the pipeline, coach, studio
and tweak paths all run unmodified.

- `text_call` dispatches on cues in the system prompt (cover letter, coach,
  interview, essay, tweak) to a canned fixture.
- `json_call` receives a `schema` but **no task name** — that is the real shape
  of `LLMProvider.json_call` in `src/providers/base.py`. It therefore
  fingerprints the schema's top-level required keys to pick a fixture, and falls
  back to a **generic schema-walker** that fabricates a schema-valid object for
  anything unrecognised. A task added later cannot crash the demo; it degrades
  to generic-but-valid output.
- Every call sleeps 0.4-1.2s. Without it, SSE run progress and the coach's
  thinking state flash past and the demo looks fake in the other direction.

### 5. Entry point

- `POST /api/auth/demo` — added to `PUBLIC_PATHS`, rate limited per IP with the
  existing `LOGIN_LIMIT`, mints an ordinary session for the demo user. Auto-seeds
  on first call if the account does not yet exist.
- Enabled when `demo_data/` exists and `DEMO_ENABLED != "0"`.
- `GET /api/health` gains `{"demo": bool}` so the (unauthenticated) login page
  knows whether to render the link.
- `GET /api/auth/me` gains `is_demo` so the shell knows whether to nudge.

### 6. Web

- **Affordance:** a muted, right-aligned line *below* the auth card — "Just
  exploring? Try the demo". Deliberately not a button: it must not compete with
  the primary call to action. Rendered only when `/api/health` reports the demo
  is available.
- **Nudge:** a slim dismissible strip in the app shell — "You're in the John Doe
  demo. AI responses are simulated, not live model calls. Sign up to use your
  own keys." — plus a small "Simulated" chip on the run, coach, interview, essay
  and AI-assist surfaces. Honesty at the point of use, not only at the door.

### 7. Rate limits

The demo user is **exempt from the per-user LLM rate limits**. Those limits exist
to cap spend, and a simulated call costs nothing; leaving them on would let one
visitor lock every other visitor out of a shared account. The per-IP limits stay.

### 8. Nightly re-seed

A shared, fully-writable account will be vandalised eventually — the re-seed is
the entire mitigation, and it only works if something runs it. A nightly cron
entry invoking `scripts/seed_demo.py --reset` is part of this change, documented
in `docs/DEPLOY-SEATTLE.md` alongside the existing deployment steps.

## Testing

- Seeder is idempotent: seed twice, assert identical row counts and tree.
- Seeder wipes: dirty the demo account, re-seed, assert the dirt is gone.
- `DemoProvider` returns schema-valid output for every registered task schema,
  including an unknown schema handled by the generic walker.
- `POST /api/auth/demo` is public, rate limited, and yields a session that can
  read the demo's own applications.
- Scope lint stays green.

## Risks accepted

1. **Vandalism between re-seeds.** The demo can look messy for up to a day.
   Accepted in exchange for a demo that feels like software rather than a
   screenshot.
2. **~1-2 MB of committed binaries**, permanent in a public repo's history.
3. **A shared session identity.** Two simultaneous visitors see each other's
   edits. Accepted; the alternative is a per-visitor cloner and reaper.
