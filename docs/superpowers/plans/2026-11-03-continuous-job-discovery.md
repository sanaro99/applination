# Continuous Job Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace manually launched discovery runs with a durable, inexpensive job feed and selected-job document generation.

**Architecture:** Source polling owns independent database leases. Public postings are shared only for identical public boards; query/credential sources are owner-specific. User matches and generation requests are tenant-scoped and independent of legacy Run status.

**Tech Stack:** Python, SQLModel/Alembic/PostgreSQL, requests, Next.js, TanStack Query.

**Spec:** `docs/superpowers/specs/2026-11-03-continuous-job-discovery-design.md` (approved November 3).

## Global Constraints

- Public source cadence 600 seconds; browser stored-feed refresh about 30 seconds.
- No paid AI calls, document generation, or owner-key fallback during discovery.
- Preserve history, applications, dismissals, and provider batch records.
- Additive migrations and owner-scoped user data; MIT attribution for adaptations.
- Background discovery flag defaults off; cached feed and selected-job generation work independently.

## Review Focus

- Failed/partial pages and 304s must not incorrectly close jobs or erase details.
- Lease expiry and competing workers must not publish stale results or duplicate paid generation.
- Same title or external ID on different boards must not hide distinct requisitions.
- Paused legacy batches and missing provider keys must not affect discovery.
- Profile edits and pause/resume must take effect without refetching everything or leaking account state.

### Task 1: Durable catalog and deterministic matching

Files: `server/discovery_models.py`, migration, `src/discovery/{identity,matching}.py`, `server/db.py`, `tests/test_discovery_store.py`, `tests/test_discovery_matching.py`.
Interfaces: catalog Source/Posting, user Subscription/Match/Generation rows; `score_job(job, search, master)` returns score/reasons; content fingerprint includes metadata.

- [x] Write tests for migrated constraints, namespace identity, metadata changes, skill boundaries, saved target rules and seniority.
- [x] Run new tests and observe failure before implementing models, migration and pure functions.
- [x] Implement additive schema and pure matching; register private models.
- [x] Run new tests and tenant scope lint; commit.

### Task 2: Source adapters and fenced discovery workers

Files: `src/discovery/sources.py`, `server/discovery_store.py`, `server/discovery_worker.py`, `tests/test_discovery_sources.py`, store/worker tests, `THIRD_PARTY_NOTICES.md`.
Interfaces: `fetch_source(kind, params, validators, request)` returns postings, completeness, validators; `discovery_tick()` claims bounded source work and rematches subscribed users, independent of Run.

- [x] Write failing adapter and worker tests for new/unchanged/304/partial data, namespaces, backoff, request budgets and stale leases.
- [x] Implement public ATS adapters (including Ashby), generic community lists, retained sources, source registry, health and freshness.
- [x] Implement due claims with leases, request caps/timeouts, source-level failure isolation, subscription synchronization and persisted rematching.
- [x] Run targeted tests; commit.

### Task 3: Scoped feed and selected-job generation

Files: `server/discovery_api.py`, `server/discovery_generation.py`, `server/single_job.py`, `server/app.py`, `server/runs.py`, `server/batch_runs.py`, auth/API tests.
Interfaces: `GET /api/jobs`, `GET/PATCH /api/jobs/discovery`, `PATCH /api/jobs/{match_id}`, `POST /api/jobs/{match_id}/generate`; durable idempotent generation requests reuse the single-job engine.

- [x] Write failing API tests proving isolation, pause/resume, applied/dismissed state, stale batches, double clicks and bounded generation.
- [x] Implement APIs, independent poller lifecycle, generation reservations, historical backfill and full-run retirement.
- [x] Run API, auth, scope, application and batch regressions; update tests whose old launch behavior is intentionally retired; commit.

### Task 4: Feed UI and user journey

Files: `web/app/jobs/page.tsx`, `/run` redirect, dashboard, API/types, nav/palette/tour/onboarding, run activity helpers.
Interfaces: paginated scoped feed, source health summary and independent generation status.

- [x] Read installed Next.js routing guides; implement job search/filter/sort, save/dismiss/undo/applied/generate actions, progress, accurate empty/stale/paused states.
- [x] Remove manual full-run and batch launch entry points; keep history and single-job actions.
- [x] Run typecheck, lint, Vitest and browser verification of the integrated user journey; commit.

### Task 5: Rollout, full validation and PR delivery

Files: example configuration/env, deployment docs, design status and PR metadata.

- [x] Document flag, source/budget behavior, migration and rollback; preserve MIT notice.
- [x] Run full backend suite, frontend checks, PostgreSQL migration/lease checks and TestSprite if configured/reachable (external TestSprite setup blocked by automatic approval review).
- [x] Dispatch one independent whole-branch reviewer. Fix substantive findings with regressions.
- [x] Push commits, update PR #94 to describe shipped behavior and evidence, and report any verification limitation explicitly.

Validation: 800 backend tests and 48 frontend tests passed; production build and TypeScript passed. PostgreSQL migration, competing source claims, generation deduplication/ownership fencing and parallel first-feed initialization passed in an isolated development schema. Browser smoke verified feed actions with fictional data and no provider keys. Changed feed/navigation/API files pass ESLint; full ESLint retains 13 existing errors and one warning in legacy UI code. No deployment or paid provider generation was performed. TestSprite environment creation was rejected by automatic approval review because it would create persistent external state and submit fictional test-account credentials; local verification completed instead.
