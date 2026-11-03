# Continuous job discovery for Applination

Status: proposed for user approval; product code has not changed.

## Intent and confirmed direction

Replace user-triggered full-pipeline runs with a continuously refreshed job
feed. Users should open Applination and see relevant jobs without first starting
a run. Discovering jobs must not depend on AI provider availability or a paused
document-generation batch. Generate resumes and cover letters only after a user
chooses a job; the user explicitly confirmed that boundary.

The desired feed refresh interval is approximately ten minutes. This is a target
for eligible source checks, not a promise that every upstream board publishes or
permits fetching at that frequency. Preserve all existing applications, files,
history, dismissals, credentials, and account isolation.

## Inspected code

- Applination main: `7ba37664434b` (fetched from `sanaro99/applination`).
- Jobtracker main: `ce35e5059ea986eb403f3c2be6130f2c1a4c3d5f`
  (`ponimark/jobtracker`). Review covered adapters and their fixtures, scheduler,
  worker, HTTP helpers, persistence, deduplication, embeddings, and matching.
- Jobtracker LICENSE is MIT, copyright 2026 Malay Joshi. Preserve its complete
  notice in `THIRD_PARTY_NOTICES.md` and identify adapted modules there. Do not
  copy its personal profile, resumes, company blocklist, or search configuration.

The existing lockout is explicit in `server/runs.py::_active_run_exists` and
`web/lib/use-latest-runs.ts::isRunActive`: waiting, batch_paused, and partial_failed
all count as active. The normal pipeline calls the AI ranker before excluding
already-applied/dismissed jobs. A dry run still spends ranking credits. The
existing `JobCache` caches generated application outputs, not the discovery feed.

## Approaches

1. Schedule the current dry-run pipeline every ten minutes. Smallest change,
   but repeatedly fetches and AI-ranks overlapping postings, retains run locks,
   and leaves the feed dependent on a paid provider. Reject for this request.
2. Adapt Jobtracker's ingestion patterns and useful adapters into Applination,
   with a persistent job catalog and per-user matches. Reuse existing auth,
   config, application tracking, and document generation. Recommended integration
   approach, consistent with the user's request to incorporate its best parts.
3. Operate Jobtracker as a separate service and import results. Reduces initial
   adapter porting, but duplicates lifecycle, config, models, and profile storage;
   its personal search assumptions still need removal. Do not use in this phase.

The matching recommendation is rules plus skill overlap in the first release.
Local semantic embeddings can later improve recall without provider credits.
This is a builder recommendation, not a user decision already made. Paid AI
ranking is not enabled implicitly.

## Product behavior

- Add `/jobs` as the primary workspace destination. Show role, company,
  locations/remote eligibility, source, posting date when known, first seen,
  last checked, match explanation, and a direct application link.
- Provide search and filters, newest/best-match sorting, save, dismiss/undo,
  mark applied, and generate documents. Saved and applied state belongs to the
  user, never to a shared posting row. Do not describe a rules score as an AI
  confidence, hiring probability, or calibrated percentage.
- Refresh the browser's stored-feed query periodically (about 30 seconds and on
  focus); this reads persisted results and never initiates a source fetch.
- Show discovery paused, fetching, last successful check, next eligible check,
  source failures, and stale results accurately. A failed source keeps its last
  known jobs with a stale indicator. One failed source cannot block others.
- Replace the manual full-run CTA and batch-mode selection with the jobs feed.
  `/run` redirects to `/jobs`. Keep run history available as historical activity;
  document-generation progress can still use internal Run IDs and existing SSE.
- Keep the single-job URL/paste workflow as a way to add a job and explicitly
  request documents. It does not initiate a discovery run.
- Discovery starts for an enabled, onboarded account with saved search targets.
  Add an explicit per-user pause/resume control. Pausing stops new discovery work
  and leaves the existing feed, applications, and document actions usable.
- Update onboarding, navigation, dashboard, command palette, tour, and empty
  states to describe discovery rather than asking the user to start a run.

## Catalog, ownership, and identity

Use additive Alembic migrations. New tables should separate these concerns:

- `DiscoverySource`: source kind, tenant/company board or query identity,
  ownership scope (shared public or user-specific credentialed search), enabled,
  base/current interval, next due, ETag/Last-Modified, success/error metadata,
  bounded failure count, lease token and expiry.
- `DiscoveredJob`: public posting fields and normalized description; stable
  source identity, source external ID, canonical URL, content fingerprint,
  first/last seen, detail-fetch time, active/stale status. Unique on source plus
  external ID (or validated URL fallback). Do not store personal matching here.
- `JobMatch`: user_id plus posting identity, rules score/reasons, profile/search
  fingerprint and scoring version, saved/dismissed/applied state, optional linked
  application and generation request. Unique per user and posting.
- `DiscoveryAttempt`: bounded operational history for source outcomes and counts;
  no API keys, complete response bodies, or resume text in logs.

Public ATS observations can be shared across accounts to avoid one identical
fetch per user. Credentialed/search-specific results are owner-scoped; include
the owner and normalized query parameters in source identity. No cross-account
cache of credentials or personalized inputs. Every private table carrying
`user_id` joins TENANT_MODELS and uses the scoping helpers; add route and scope
tests. Public catalog access still passes authenticated, scoped feed endpoints.

Do not transplant Jobtracker's global raw-external-ID dedup set: independent ATS
boards can reuse an ID. Namespaced IDs and normalized direct URLs are the strong
identity signals. Company/title similarity may suggest aliases but cannot erase
different requisitions or locations. Preserve variants and prefer a verified
direct employer application URL for display. Do not overwrite an existing full
description with an empty list-page summary.

Fingerprint title, description, location, remote status, employment type, and
application URL, so non-description edits also trigger rematching. Update
`last_seen_at` for unchanged postings after successful observations, including
complete 304 responses. Partial or failed pagination cannot prove closure. Mark
missing postings inactive only after a complete authoritative snapshot or an
explicit upstream closed indication. Label unverifiable old records stale.

## Discovery execution and cost bounds

Discovery has its own worker and database-backed leases, completely independent
of Run status, batch state, document-provider authentication, and document output
directories. Keep HTTP work off the API event loop. The implementation can use a
dedicated Python entrypoint plus an independent API background dispatcher; it
must have one lease owner per source even with multiple API instances.

Persist due times and leases; atomically claim work and fence updates by token.
Use bounded worker concurrency, timeouts, request/page caps, startup jitter, and
per-host rate limits. Expired leases recover after crashes. Cancellation/shutdown
must release or expire claims without publishing a partial snapshot as complete.
Process sources fairly so one long company board cannot starve others.

Default ordinary public-board cadence: 600 seconds. Check eligibility each
minute. Each source may use a slower cadence, with Retry-After and backoff on
429/5xx/timeouts. Keep immutable base interval separate from current backoff;
backoff must never shorten a source's base interval. Stop automatic retries on
authentication failures until configuration changes. Persist ETag/Last-Modified
per exact request URL/page. A 304 on one page cannot stand for an entire paginated
board. Never bypass authentication, paywalls, or challenge pages.

Reuse Jobtracker's two-step pattern where detail calls are expensive: fetch list,
filter obvious irrelevant entries and inspect IDs/versions, then fetch new or
changed details. Refresh details periodically even when an ID is unchanged so
edits are not missed forever. Incomplete jobs remain visible as incomplete and
cannot start generation until there is an adequate stored description.

Paid/quota-limited aggregators do not enter a ten-minute schedule by default.
Existing JSearch can make three requests per country per fetch. Require explicit
background opt-in with an owner-scoped daily request budget and slower interval;
reserve request budget atomically before each HTTP attempt, including retries
and pages. Exhaustion skips work until budget renewal and leaves cached results
available. No server-owner API key fallback.

Rules matching, feed reads, and refresh ticks make zero calls to `Tailor`,
`get_task_chains`, paid embedding APIs, or document generation. Cache scores by
job fingerprint plus user profile/search fingerprint plus scoring version. A
profile edit rematches stored jobs; it does not refetch all sources.

## Matching and optional local models

Apply saved job-type, location/remote, keyword, and seniority rules before
scoring. Reuse `src/target_rules.py` and candidate profile guards. Adapt the
boundary-aware skill alias/requirement extraction ideas from Jobtracker, extended
to each user's actual master-resume skills rather than hardcoded DE/ML targets.
Return factual reasons such as matched skills and role keywords. Preserve unknown
location/seniority/experience as unknown; do not invent eligibility.

First release: rules and skill overlap on CPU, no model dependency. If enabled in
a later phase, a small pinned local embedding model runs in a separate bounded
worker, computes vectors only for changed jobs/profiles, and caches by model
version as well as content. No download or inference on API/feed requests and no
paid fallback if the model is unavailable. Keep the feed usable with rules scores
while embedding work is pending. Local inference uses host CPU/RAM, even though
it consumes no provider credits. pgvector and cross-encoder reranking are optional
follow-up deployment changes, not prerequisites for the first feed.

## Jobtracker reuse priorities

Adapt code with attribution and fixture-based coverage, not personal config:

1. Source adapter contract, fetch metadata, conditional requests, two-step detail
   retrieval, content fingerprints, and source-health records.
2. Ashby public posting adapter and generalized GitHub new-grad lists. Retain
   Applination's existing Greenhouse, Lever, Remotive, Muse, Himalayas, Simplify,
   and optional aggregator coverage.
3. SmartRecruiters and Workday, with detail retrieval and completeness tests.
   Jobtracker's Workday implementation reads list data and caps at 500 jobs;
   verify and correct truncation/detail availability before enabling it.
4. Direct employer connectors (Amazon/Microsoft/JPMorgan), parameterized from
   saved search/country rather than its US/data-engineering defaults. Validate
   live response shapes and links before enabling each connector.

JobSpy, additional scraping sources, local embeddings, and the cross-encoder are
follow-ups after the durable feed and new public ATS adapters meet acceptance.
Do not bring its Discord notifier, separate web UI, personal blocklists, or
mandatory Redis/pgvector infrastructure into this release.

## Retiring runs and avoiding the original failure

- Stop accepting new full-pipeline immediate, scheduled, or batch submissions
  through `/api/runs`; return a clear retirement response pointing to `/jobs`.
  Preserve get/list/log/stream/history for prior work.
- Disable dispatch of legacy scheduled discovery/full runs and new batch paid
  submissions. Existing unresolved provider batches remain recorded for manual
  reconciliation; deploying this feature does not silently cancel, resubmit,
  delete, or claim provider cancellation of them.
- Preserve already-running document work at cutover. Historical waiting,
  batch_paused, and partial_failed rows do not block discovery, feed access, or
  on-demand generation. Remove their use as a global workspace busy signal.
- Document generation uses a separate bounded queue, not the discovery lease.
  Atomically reserve `(user_id, posting_id)` to make double clicks/retries
  idempotent. If capacity is full, show queued status; errors permit an explicit
  retry. Generation failure never marks a job applied or removes its feed card.
- Reuse stored JD and existing document engine for selected jobs, link outputs
  to that user's application, and continue to enforce filesystem containment.
- Backfill useful historical RankedJob observations into the catalog without
  calling AI or network services. Transfer dismissals and application links per
  user. Keep duplicate/historical rows intact; do not rewrite old run foreign keys.

## Validation and rollout

Verify migrations on PostgreSQL as well as the repository's SQLite test harness.
Test source fixtures, tenant isolation, duplicate IDs on different boards,
multiple same-title requisitions, empty detail protection, changed metadata,
unchanged/304 freshness, partial pagination, stale/closed semantics, independent
source failures, Retry-After, request budgets, process restart, and competing
workers. Explicitly prove waiting/paused/failed legacy batches cannot block feed
updates or selected-job generation. Patch AI entrypoints to raise in discovery
tests, demonstrating refreshes make no provider calls.

Exercise UI discovery, filters, dismiss/undo, saved/applied state, generation
progress, retry and duplicate clicks, empty configuration, stale results, and
navigation/tour redirects. Run existing auth/scope/run/application tests plus
frontend checks. Fixture tests validate parsing; bounded live checks validate a
source only when network access is available, and source enablement must report
that distinction accurately.

Ship behind an install-wide `CONTINUOUS_DISCOVERY_ENABLED` flag, initially off.
The flag gates new source-fetch and matching claims only. With it off, `/jobs`
still serves migrated/cached results and saved state, and selected-job document
generation remains available through its independent queue. Show discovery as
paused by the administrator. Retired full-run entrypoints and scheduled batch
dispatch stay retired in both flag states; turning the flag off must not revive
legacy work. This flag behavior is a builder decision, not a user stipulation.
Deploy additive schema and application code first, retain a database backup, then
enable for an owner smoke test before general rollout. Keep paid sources off
unless opted in. Verify worker health, feed freshness and zero discovery AI calls.
Rollback disables the flag and new workers; additive rows and all historical
applications stay intact. Restoring the old run UI is a version rollback choice,
not automatic retry of old scheduled or provider batches.

## Decisions left to the builder

Exact table/API names, pagination implementation, worker pool mechanism, visual
layout within existing components, skill scoring weights/version, and source
enablement UX may be settled during implementation. Use existing Python,
SQLModel/Alembic/Postgres and Next.js/TanStack infrastructure. Start with the
first-release scope above; do not require a new vector database or a paid model.

## Source references

- [Applination run guard](https://github.com/sanaro99/applination/blob/7ba37664434b53b07adbc3f9c0ff06d5e204d731/server/runs.py)
- [Jobtracker license](https://github.com/ponimark/jobtracker/blob/ce35e5059ea986eb403f3c2be6130f2c1a4c3d5f/LICENSE)
- [Source registry](https://github.com/ponimark/jobtracker/blob/ce35e5059ea986eb403f3c2be6130f2c1a4c3d5f/src/jobtracker/sources/registry.py)
- [Adaptive scheduler](https://github.com/ponimark/jobtracker/blob/ce35e5059ea986eb403f3c2be6130f2c1a4c3d5f/src/jobtracker/ingest/scheduler.py)
- [Ingestion worker](https://github.com/ponimark/jobtracker/blob/ce35e5059ea986eb403f3c2be6130f2c1a4c3d5f/src/jobtracker/ingest/worker.py)
- [Persistence and aliases](https://github.com/ponimark/jobtracker/blob/ce35e5059ea986eb403f3c2be6130f2c1a4c3d5f/src/jobtracker/db/repo.py)
- [Embedding implementation](https://github.com/ponimark/jobtracker/blob/ce35e5059ea986eb403f3c2be6130f2c1a4c3d5f/src/jobtracker/enrich/embedder.py)
