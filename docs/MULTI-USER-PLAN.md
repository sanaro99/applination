# Multi-user Applination — auth, tenant isolation, Postgres

Working plan for turning Applination from a single-tenant tool into one anyone
can sign up for. Three PRs, each independently deployable. **Read this before
starting work on any of them.**

Status at a glance:

| PR | Scope | State |
|---|---|---|
| 1 | Postgres + Alembic baseline | **Merged** (#26, 2026-08-13) |
| 2 | Users, auth, tenant columns | Not started |
| 3 | Per-user filesystem, remaining traps | Not started |

---

## Context

Applination was single-tenant by construction. No auth of any kind, and all
state a global singleton: `config.yaml`, `master_data/`, `output/`, and a
database whose tables had no owner column. The goal is per-user data, per-user
API keys, and no way for one user to reach another's anything.

**The primary correctness risk is a missed tenant filter.** There are ~83 DB
query sites across the routers. One unscoped `select()` is a cross-tenant data
leak. The plan engineers against that specifically rather than relying on care.

---

## Decisions — settled, do not relitigate

| Decision | Choice | Why |
|---|---|---|
| API keys | **BYOK** — each user brings their own | Shared keys means the owner funds every signup's LLM spend. BYOK also removes the whole quota/billing subsystem. |
| Signup | **Open to anyone** | Considered invite-gating and deliberately rejected it. Risk is carried by rate limits + caps, not by a gate. |
| Existing data | **Additive backfill to user #1** | Nullable column → backfill → NOT NULL. Never a wipe and reseed. |
| Database | **Postgres**, from PR 1 | Writing PR 2's migrations against SQLite would mean `batch_alter_table` everywhere, then a rewrite. |
| Shape | **Three PRs** | `main` is protected and auto-deploys; a big-bang PR risks production. |
| CLI | **Owner-operated**, gains `--user <email\|id>` | Keeps the debugging path without making it user-facing. |

### On open signup

Anyone can register in front of a scraper pipeline, a shared worker, and disk.
What carries that risk instead of a gate:

- Per-user concurrent-run cap (1) and a global cap (2) in the scheduler
- Round-robin dispatch so one user cannot starve others
- Per-user disk quota checked before a run writes
- Rate limits on signup and every LLM-calling endpoint
- BYOK, so a user's LLM spend is their own

Remaining exposure is disk and scraper egress, and both are capped.

---

## Verified facts — do not re-derive

- **~83 DB query sites** across the routers (`chat.py` 25, `runs.py` 17,
  `inbox.py` 6, `applications.py` 6, long tail).
- **`Setting` needs a primary-key change, not just a column.** Its PK is bare
  `key`, so Gmail OAuth tokens, the onboarding flag, and inbox processed-ids
  share one global namespace. Must become `(user_id, key)`.
- **Status enums are `Enum(native_enum=False, length=32)`** in `server/db.py` —
  VARCHAR storage, but reads return enum members. Do **not** map them to a bare
  `String`; that broke every `status.value` reader and 500'd `/api/stats`.
  `tests/test_db_status_types.py` guards this.
- **`web/lib/api.ts` builds `/files/...` URLs directly** and uses `EventSource`
  for the SSE run stream (needs `withCredentials: true`).
- **Dev is cross-origin.** `localhost:3000` → `127.0.0.1:8000` means a
  `SameSite=Lax` cookie will not be sent. Production is already same-origin via
  Traefik; dev needs a `rewrites()` proxy in `web/next.config.ts`.
- **Every web page is `"use client"`**, so auth gating is a client component
  mirroring `web/components/onboarding-gate.tsx`, not Next middleware.
- **`process_job()` already takes `day_root: Path`** and computes stored paths
  relative to `day_root.parent` (`src/main.py`), so per-user output is a matter
  of passing a different root — not a rewrite.

---

## PR 1 — Postgres + Alembic baseline (merged)

No behavior change; still single-tenant. What shipped:

- `server/db.py` engine from `DATABASE_URL`, `pool_pre_ping=True` (pipeline runs
  occupy long-lived daemon threads and hold connections idle).
- Deleted the hand-rolled `_migrate()` / `_ADDED_COLUMNS` mechanism. `init_db()`
  now only asserts the database is migrated.
- Alembic baseline in `server/migrations/`, entrypoint runs `alembic upgrade head`
  before uvicorn.
- `scripts/sqlite_to_postgres.py` — copies in FK order preserving primary keys,
  then fast-forwards sequences. Refuses a non-empty target. Atomic.
- `applination-db` (postgres:18-alpine) in the compose file, Watchtower disabled
  on it deliberately.
- `.gitattributes` pinning LF — `core.autocrlf=true` would otherwise ship
  `docker-entrypoint.sh` as CRLF and the container dies with `bad interpreter`.

### Lessons that carry forward

Two bugs surfaced **only** when tested against a real Postgres:

1. `sa_type=String` stored VARCHAR correctly but made reads return plain `str`,
   breaking seven `status.value` call sites. Fixed with
   `Enum(native_enum=False)`.
2. The sequence fast-forward crashed on `setting` — SQLModel's `AutoString`
   raises `NotImplementedError` from `.python_type`. Use
   `isinstance(type, Integer)`.

**Neither was reachable from the SQLite smoke test.** Verify against the real
target, and prove new tests fail against the broken implementation before
claiming they pass.

---

## PR 2 — Users, auth, and tenant columns

New files: `server/auth.py`, `server/scoping.py`, `server/tests/test_authz.py`,
`web/app/(auth)/login/page.tsx`, `.../signup/page.tsx`,
`web/components/auth-gate.tsx`.

### Models

```
User          id, email (unique, lowercased), password_hash, created_at,
              is_owner: bool, disabled: bool
UserSession   token_hash (PK), user_id, created_at, expires_at, last_seen_at
UserSecret    (user_id, name) composite PK, ciphertext
```

`UserSecret` holds LLM API keys and the Gmail OAuth token, Fernet-encrypted
under a server-held `APPLINATION_SECRET_KEY`. Never in YAML. Password hashing is
**argon2id** via `argon2-cffi`.

Sessions are **server-side and opaque** — random 32 bytes, SHA-256 hashed at
rest — so logout and password change can revoke them. Cookie
`applination_session`: `httpOnly`, `Secure`, `SameSite=Lax`, `Path=/`.

### Default-protected — two independent layers

1. `dependencies=[Depends(require_user)]` on every `include_router` in
   `server/app.py`.
2. **Plus** middleware that 401s any path not in an explicit `PUBLIC_PATHS` set
   (`/api/health`, `/api/auth/login`, `/api/auth/signup`, `/docs`,
   `/openapi.json`).

Layer 2 exists because layer 1 fails open for any router added later that
forgets the dependency. A test enumerates `app.routes` and asserts each either
401s unauthenticated or is explicitly public — so making a route public becomes
a deliberate, reviewable act.

### Tenant columns

`user_id` FK on `run`, `application`, `rankedjob`, `chatsession`,
`chatmessage`, `savedanswer`; `setting` PK rebuilt as `(user_id, key)`.

`user_id` is **denormalized onto child tables** rather than joined through the
parent — direct filtering is harder to get wrong — and the parent's ownership is
re-verified on insert.

Migration, strictly additive:

```
1. ADD COLUMN user_id INTEGER NULL                    (all 7)
2. INSERT the owner User, seeded from config.yaml's `user:` block.
   Password set via a one-time console-printed reset, never a literal.
3. UPDATE <t> SET user_id = 1 WHERE user_id IS NULL   (all 7)
4. SET NOT NULL + FK + composite index (user_id, id)
5. setting: rebuild PK as (user_id, key)
```

Downgrade drops the columns. Never a data delete.

### Closing the 83 query sites

`server/scoping.py` is the only sanctioned way to touch a tenant table:

- `owned(stmt, Model, user)` → appends `.where(Model.user_id == user.id)`
- `get_owned(s, Model, obj_id, user)` → `s.get` + ownership check, **404 on
  mismatch** (not 403 — don't confirm the row exists)

Then a deliberate sweep, as a checklist item:

```bash
grep -rn "select(\|s\.get(" server/ --include=*.py
```

Every hit must either route through `scoping.py` or carry
`# noscope: <reason>`. Legitimate exceptions: `User` / `UserSession` lookups and
the scheduler's cross-user dispatch query. A test fails the build on an
unannotated bare `select()` against a tenant model.

### Rate limiting

`slowapi`, in-process (single container). Per-IP on `/api/auth/signup` and
`/api/auth/login`; per-user on every LLM-calling endpoint (`chat`, `studio`,
`tweak`, `single_job`, the `ops` provider test).

### Frontend

- `http()` in `web/lib/api.ts` gains `credentials: "include"`; 401 → `/login`.
- `auth-gate.tsx` querying `/api/auth/me`.
- `rewrites()` in `web/next.config.ts` so dev is same-origin; `API_BASE`
  defaults to `""`.
- `EventSource` gains `{ withCredentials: true }`.

### Acceptance criteria

`server/tests/test_authz.py` is the bar. Users A and B with real data. For
**every** tenant resource — runs, applications, ranked jobs, chat sessions, chat
messages, saved answers, settings, config, master data:

- A GET of B's object by id → 404
- A mutation of B's object → 404, **and B's row is unchanged**
- A's list endpoints never contain B's rows
- Unauthenticated → 401
- Creating a child under B's parent (a message in B's chat session) → 404

Plus the route-enumeration test and the scope-lint test.

---

## PR 3 — Per-user filesystem and the remaining traps

New file: `server/user_paths.py`.

```
data/users/<user_id>/
  config.yaml
  master_data/{resume.yaml,bio.md,stories/,cover_letters/examples/}
  output/<date>/<Company_Role>/
```

`master_data/guidelines/` and `master_data/templates/` stay in the repo — they
are committed and generic, read globally, never copied per user.

### `load_config` becomes user-scoped

`load_config(user)`, `update_config(user, mutator)`, `output_root(user)`. **Drop
the `@lru_cache` on `output_root`** — it is a correctness bug the moment there is
more than one user. Ripples to ~25 call sites across `chat.py`, `runs.py`,
`inbox.py`, `ops.py`, `reminders.py`, `single_job.py`, `studio.py`, `tweak.py`,
`applications.py`, `pricing.py`, `gmail_auth.py`, `onboarding.py`.

Secrets are **merged in at read time**: `load_config(user)` decrypts that user's
`UserSecret` rows into `llm.<provider>.api_key` and `inbox.*`. Never written to
YAML on disk, and stripped before `get_config` returns to the browser.

### `src/pipeline.py` — stop reading global paths

`pipeline.py` hardcodes `ROOT / "master_data" / ...` five times;
`server/coach_context.py`, `server/config_api.py`, and `server/single_job.py` do
the same. Add an explicit `paths: UserPaths` parameter to `run_pipeline()` and
thread it through.

### Trap: the `/files` StaticFiles mount

`server/app.py` mounts the entire output root — any user could read another's
resume by guessing a path. **Delete the mount.** Replace with
`GET /api/files/{rel_path:path}` that resolves against the user's output root,
calls `.resolve()` and asserts `is_relative_to(user_output_root)` (traversal
guard), then returns `FileResponse`.

`web/lib/api.ts` builds `/api/files/...`. Cookies are sent on same-origin
`<img>`/`<a>` requests, so downloads keep working. Leave the Traefik `/files`
prefix rule alone — harmless, and avoids touching routing.

### Trap: the Setup page writing global config

Under the per-user layout there is no global `config.yaml` left to protect.
`config_api.py` resolves through `UserPaths` and asserts the resolved path is
under the user's directory before writing. Keep the existing story-name
rejection of `/`, `\`, and leading `.`.

### Trap: the global scheduled-run poller

`_scheduled_run_poller` (`server/app.py`) and `dispatch_due_scheduled_runs`
(`server/runs.py`) dispatch globally, and `_active_run_exists()` blocks
*everyone* when *anyone* runs.

Rewrite: `_active_run_exists(user_id)` for a per-user cap of 1, plus a global
`MAX_CONCURRENT_RUNS` (default 2, env-tunable). Order by `scheduled_for` but
dispatch **round-robin across distinct users**.

### Trap: provider env-var fallback spending the owner's keys

Six identical lines in `src/providers/` (`claude`, `deepseek`, `gemini`,
`mistral`, `nim`, `openrouter`), all `api_key or os.environ.get(...)`. Gate every
one behind `ALLOW_ENV_API_KEYS`, **default off**. With it off, a missing per-user
key raises a clear "no API key configured" error instead of silently billing the
server owner.

### CLI

`src/main.py` and `src/tweak.py` gain `--user <email|id>`, defaulting to the
owner. Both resolve `UserPaths` and decrypt secrets through the same code path
the server uses.

### Deploy

Compose bind mounts collapse from four to one — everything lives under `data/`.
Update `deploy/applination.compose.yaml` and `docs/DEPLOY-SEATTLE.md` in the same
PR, including a rollout runbook. `scripts/migrate_to_multiuser.py` moves the
three host directories into `data/users/1/` and rewrites the absolute
`Application.folder_path` values in the same transaction. Idempotent and
`--dry-run`-able. The move is a rename within one ZFS dataset, so it is cheap
regardless of how large `output/` is.

---

## Rollout

**The Seattle instance is intentionally stopped** until all three PRs have
landed. Merging to `main` still builds and publishes images, but nothing is
serving, so a merge cannot take production down and downtime between now and the
final cutover is expected.

This means the migrations do **not** have to be run one PR at a time. Do them as
a single maintenance window once PR 3 merges, in this order:

1. Snapshot the `appconfig` dataset (the one reversible step everything else
   depends on).
2. Update `applination.env` — `POSTGRES_PASSWORD`, `DATABASE_URL`,
   `APPLINATION_SECRET_KEY`.
3. Create `pgdata/`, update the app YAML from
   `deploy/applination.compose.yaml`, start the stack. Postgres initialises and
   the API runs `alembic upgrade head`.
4. `scripts/sqlite_to_postgres.py --dry-run`, then for real (PR 1's runbook,
   `docs/DEPLOY-SEATTLE.md`).
5. `scripts/migrate_to_multiuser.py --dry-run`, then for real (PR 3).
6. Set the owner password, restart, verify.

The old `data/app.db` is never deleted and remains the rollback path.

---

## Operational secrets

PR 2 introduces **`APPLINATION_SECRET_KEY`**, the Fernet key encrypting every
user's LLM API keys and Gmail token. If it is lost, all stored secrets become
undecryptable and every user must re-enter their keys.

Generate once (`openssl rand -base64 32`), put it in `applination.env` on the
NAS, and **back it up somewhere outside the ZFS snapshot** — a snapshot that
loses the pool loses the key with it.

Same discipline for `POSTGRES_PASSWORD`, added in PR 1.

---

## Working conventions

- **Issue → branch → PR.** `main` is protected; every merge auto-deploys to the
  Seattle NAS in ~2 minutes. Never push to `main`.
- **Never `git add -A` blindly.** `master_data.tgz` / `output.tgz` may sit
  untracked in the repo root and contain personal data. This repository is
  **public**. They are gitignored now, but check what you stage.
- **Verify against the real target.** PR 1's two bugs were both invisible to the
  SQLite proxy. Prove a new test fails against the broken implementation before
  claiming it passes.
- Personal data is gitignored: `config.yaml`, `master_data/resume.yaml`,
  `bio.md`, `stories/*.md`, `cover_letters/examples/*`.

## Local environment

- **PostgreSQL 18 installed natively** (service `postgresql-x64-18`, port 5432);
  pgAdmin available. Dev connection:
  `postgresql+psycopg://applination:applination_dev@127.0.0.1:5432/applination`
  (throwaway local credential, not a secret).
- **`docker pull` does not work on this network** — `*.cloudfront.net` is
  blocked, so image blob fetches fail for both Docker Hub and the ECR mirror.
  Use the native Postgres. Docker itself runs; only registry blobs are blocked.
- **Tests use their own temp SQLite databases** via `tests/conftest.py::migrate()`,
  which runs the real Alembic migrations, so a migration that drifts from the
  models fails the suite. Baseline after PR 1: **106 passing**.
- Reseed the dev database: drop/recreate schema `public` →
  `alembic upgrade head` → `python scripts/sqlite_to_postgres.py --sqlite data/app.db`.
