# Continuous discovery

Applination's `/jobs` feed replaces manually launched full-pipeline runs.
Discovery checks eligible public sources around every ten minutes, stores public
postings, and matches them against each account's saved search and resume skills
without calling an AI provider. Browser refreshes read the stored feed. Generate
documents only for a job selected by the user; generation has an independent,
durable queue with two workers and at most one worker per user.

## Rollout

1. Back up PostgreSQL and the per-user data directory.
2. Deploy the API and web images with `CONTINUOUS_DISCOVERY_ENABLED=0`. The normal
   container entrypoint runs the additive Alembic migration. Do not downgrade or
   recreate the production database.
3. Open `/jobs` as the owner. Historical ranked observations and dismissals are
   imported additively on first access. Application files and old run IDs stay
   intact. Verify save/dismiss, filters and an explicitly chosen document action.
4. Set `CONTINUOUS_DISCOVERY_ENABLED=1` in the API runtime environment and restart
   the API. The independent dispatcher scans once per minute, using up to four
   fetch workers and at most 64 due sources per tick. Cold catalogs and throttled
   sources can take longer than ten minutes. Source status shows actual checks.
5. Verify source successes, next check times, matches, and generation progress.
   A paused/failed old provider batch must not prevent browsing or generation.

Flag rollback: set `CONTINUOUS_DISCOVERY_ENABLED=0` and restart. This stops new
fetch/matching claims, while cached jobs, private state and document generation
remain usable. It does not revive old schedules or resubmit provider batches.
An application-version rollback is separate; keep the additive schema and data.

## Sources and cost

Saved Config source switches and company slugs drive subscriptions. Identical
public boards share observations; keyword/credentialed searches are owned by one
account. Source kinds include existing Greenhouse, Lever, Remotive, Muse,
Himalayas, Simplify lists, and the new Ashby and generalized GitHub-list adapters.
SmartRecruiters and Workday are available behind explicit source switches. Their
list/detail fetches are bounded; partial results never close unobserved jobs.
Additional direct-employer adapters and JobSpy are not enabled in this release.

Use Config's Advanced YAML to configure new source kinds; see
`config.example.yaml` for shapes. Empty Ashby configuration defaults to a small
public-board list. Explicit `enabled: false` disables it. GitHub list entries
accept `repo: owner/name` and `branch`. Posting dates are shown only when provided;
first-seen and last-check dates are separate. A missing full description keeps a
job visible but requires the user to supply it through Single job before document
generation. Workday/SmartRecruiters detail caches refresh at most daily, with ten
detail calls per board check. Enable individual boards only after validating them
from the deployment network; fixture parsing tests alone do not prove availability.

JSearch/Adzuna require both their ordinary `sources.<kind>.enabled` switch and
`discovery.aggregators_enabled: true`. The default shared daily request budget is
10 per account, configurable via `discovery.aggregator_daily_budget` (1–1000).
These searches run no faster than every six hours. Every outbound request
reserves budget before accessing the network. API keys are loaded only for that
owner at call time and are never stored in source parameters. Authentication
errors halt a source until its stored credential revision changes. Other errors
back off, honoring Retry-After; existing jobs remain readable as stale.

The local-model and pgvector approach from Jobtracker remains a later extension.
This release uses explainable rule/skill matching and no embedding model or paid
AI fallback. Historical imported scores are labeled separately until rematched.
Adapted discovery work is credited in `THIRD_PARTY_NOTICES.md`.

## Recovery and limits

Source claims expire after three minutes and are renewed before network calls;
publication checks the claim token. Failures and partial snapshots cannot erase
existing descriptions. Exact direct application URLs share a feed card and user
actions, while different requisition URLs stay separate. Per-user matching scans
the most recent 10,000 subscribed observations per tick. Historical import is
bounded to the most recent 5,000 ranked observations per account.

Document requests survive restarts. A worker interrupted after dispatch is marked
as an error after lease expiry rather than automatically replaying potentially
billable work. Recovery first reconciles any application already saved by that
request, including linking its documents back to the feed. Expired workers are
fenced before provider steps and database publication; a retry cannot let the
old worker overwrite its run. The UI offers explicit retry. A provider may have processed the
interrupted request, so retry can create another charge. Completed applications
and files are not deleted. An unresolved old provider batch remains available in
run history for manual reconciliation; it does not hold a discovery or document
slot. New `POST /api/runs` calls return HTTP 410 with a link to `/jobs`.
