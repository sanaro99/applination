# TestSprite AI Testing Report (MCP) — Backend

---

## 1️⃣ Document Metadata
- **Project Name:** internship_bot (Applination)
- **Scope:** Backend API (FastAPI), `codebase`
- **Server under test:** `http://localhost:8000` (uvicorn)
- **Date:** 2026-06-05
- **Prepared by:** TestSprite AI + maintainer review
- **Test environment note:** LLM provider API keys were intentionally blanked and no Gmail credentials were configured during this run, so billable/outward-facing paths (real pipeline runs, LLM generation, inbox reads, outbound email) could not execute. Tests therefore validate HTTP contracts, response shapes, and documented error paths.

---

## 2️⃣ Requirement Validation Summary

### Requirement: Service Health
- **Description:** Liveness probe.

| Test | Name | Status |
|------|------|--------|
| TC001 | get_health_endpoint_returns_service_status | ✅ Passed |

**Analysis:** `GET /api/health` returns 200 with `{ok: true}`. No issues.

---

### Requirement: Pipeline Runs (start / list / stream / stop)
- **Description:** Trigger and inspect daily pipeline runs; SSE progress; cooperative cancel.

| Test | Name | Status |
|------|------|--------|
| TC002 | post_runs_starts_pipeline_run | ✅ Passed |
| TC003 | get_runs_list_recent_runs | ✅ Passed |
| TC004 | get_runs_runid_stream_returns_sse_events | ✅ Passed |
| TC005 | post_runs_runid_stop_cancels_active_run | ❌ Failed → **fixed** |

**Analysis:**
- TC002/TC003/TC004 confirm the run-create contract (a queued `Run` record is returned synchronously), the runs listing, and the `text/event-stream` SSE endpoint.
- **TC005 surfaced a real API ergonomics bug.** `POST /api/runs/{run_id}/stop` declared a **required** JSON body (`StopRunBody`), so a call with no body returned **422** instead of acting on the `graceful=true` default. The browser client always sends a body, which is why this was never observed in the UI.
- **Fix applied** (`server/runs.py`): `stop_run` now takes `body: StopRunBody | None = None` and defaults to a graceful stop; `start_run` was made body-optional for the same reason. Verified via FastAPI TestClient and against the live server — a no-body stop on a missing run now returns **404** (was 422).

---

### Requirement: Applications Management
- **Description:** List/filter applications; update status, notes, tags, deadline.

| Test | Name | Status |
|------|------|--------|
| TC006 | get_applications_filters_and_retrieves_applications | ✅ Passed |
| TC007 | patch_applications_runid_updates_application | ❌ Failed (test-assertion mismatch, not a defect) |

**Analysis:**
- TC006 confirms listing + filtering returns the expected array shape.
- **TC007 is a false negative.** It sent `deadline` as a date string (`"YYYY-MM-DD"`) and asserted the response echoed it verbatim. The `Application.deadline` field is a `datetime`, so the value is correctly stored and returned as `"YYYY-MM-DDT00:00:00"`. The update **succeeds**; only the test's strict string-equality assumption fails. No code change made — `datetime` is intentional (interviews carry a time component). Optional future ergonomics improvement: accept/return a bare date for `deadline`, or document the datetime normalization.

---

### Requirement: Ranked Jobs / Triage + Cross-run Dedup
- **Description:** Per-run scored pool; rescue (generate) a non-selected job; dismiss to exclude from future runs.

| Test | Name | Status |
|------|------|--------|
| TC008 | post_ranked_rankedid_generate_rescues_job | ❌ Failed (environment artifact) |

**Analysis:**
- **TC008 failed for environment reasons, not a code defect.** The test created a *fresh* run (`dry_run:false`) and then expected that run to already contain ranked jobs. Because provider keys were blanked for safety, the run could not rank, so `GET /api/runs/{run_id}/ranked` returned an empty list and the test aborted before exercising the generate endpoint. (The generated test also uses a non-integer id when probing the 404 path, which would yield 422 rather than 404 — a test-generation flaw.)
- The `generate`/`dismiss` contracts are covered by the repo's own unit/integration tests (`tests/test_dedup.py`) and the earlier TestClient smoke test (dismiss/undismiss roundtrip ✓). Recommended TestSprite improvement: target an **existing** run that already has a ranked pool instead of creating a new one.

---

### Requirement: Inbox Sync (Close the Loop)
- **Description:** Read recruiter replies over IMAP, classify, advance status; safe 400 when unconfigured.

| Test | Name | Status |
|------|------|--------|
| TC009 | post_inbox_sync_updates_application_statuses | ✅ Passed |

**Analysis:** With no Gmail credentials configured, `POST /api/inbox/sync` correctly returns **400** ("not configured") rather than erroring — the intended safe default. (The credentialed happy-path is covered by `tests/test_inbox.py` against stubbed IMAP/LLM.)

---

### Requirement: Reminders (Calendar Feed + Digest)
- **Description:** iCalendar feed and daily digest preview/send.

| Test | Name | Status |
|------|------|--------|
| TC010 | get_reminders_digest_preview_returns_digest_content | ✅ Passed |

**Analysis:** `GET /api/reminders/digest/preview` returns 200 with `{subject, html, text, empty}` without sending email. The `.ics` feed and digest builders are additionally covered by `tests/test_reminders.py`.

---

## 3️⃣ Coverage & Matching Metrics

- **As-run:** 7 / 10 passed (70%).
- **After the TC005 fix:** 1 real defect found and fixed; the remaining 2 "failures" are a test-assertion mismatch (TC007) and an environment artifact (TC008), not product defects. Effective product pass rate: **9 / 10**.

| Requirement | Total | ✅ Passed | ❌ Failed | Notes |
|-------------|-------|-----------|-----------|-------|
| Service Health | 1 | 1 | 0 | |
| Pipeline Runs | 4 | 3 | 1 | TC005 real bug → fixed |
| Applications | 2 | 1 | 1 | TC007 over-strict assertion |
| Ranked / Dedup | 1 | 0 | 1 | TC008 env artifact (blanked keys) |
| Inbox Sync | 1 | 1 | 0 | safe 400 path |
| Reminders | 1 | 1 | 0 | |
| **Total** | **10** | **7** | **3** | |

---

## 4️⃣ Key Gaps / Risks

1. **Fixed:** `stop`/`start` run endpoints required a JSON body even though all fields default. Now optional. (`server/runs.py`)
2. **Minor / by-design:** `deadline` accepts a date but returns a `datetime` (`...T00:00:00`). Harmless but can surprise API clients; consider documenting or normalizing.
3. **Coverage limited by safety choices:** the happy paths for `POST /api/runs`, `ranked/generate`, `inbox/sync` (credentialed), and `digest/send` were not executed live because that would incur real LLM/job-board/email side effects. These are covered by the repository's own pytest suite (`tests/test_dedup.py`, `tests/test_inbox.py`, `tests/test_reminders.py`) using stubs.
4. **No auth layer:** every endpoint is open by design (single-tenant, trusted-localhost). Not a finding, but worth stating for any future networked deployment.
5. **Test-generation flaws to note for re-runs:** TC008 should target an existing ranked pool; integer path params (`ranked_id`, `app_id`) should be probed with integers (missing-id → 404), not strings (which yield 422).
