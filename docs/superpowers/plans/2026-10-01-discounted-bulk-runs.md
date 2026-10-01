# Discounted Bulk Runs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for native execution, or superpowers:subagent-driven-development if the user selects delegation. Implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Offer discounted asynchronous bulk generation through OpenAI, Claude, and Gemini without adding billable work to ordinary runs.

**Architecture:** Preserve the existing immediate pipeline and add an opt-in durable batch coordinator. Shared pure request builders and result reducers expose ready work without performing network calls; provider adapters submit and retrieve that work. The existing server scheduler resumes persisted stages and publishes validated artifacts idempotently.

**Tech Stack:** Python, FastAPI, SQLModel/Alembic, existing provider SDKs, Next.js/React, pytest, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-01-discounted-bulk-runs-design.md`

## Global Constraints

- Existing runs and single-job actions default to immediate mode. Existing saved configurations need no changes.
- Keep existing `text_call` and `json_call` contracts unchanged.
- Immediate mode retains provider selection, per-task model overrides, prompts, schemas, reasoning settings, token limits, cache behavior, quality checks, and retry limits. It must not initialize batch adapters, submit batch requests, poll batches, or make additional AI calls.
- Batch mode cannot silently promote a model, increase a token budget, add an AI planning step, or fall back to synchronous paid generation.
- Completed items are never resubmitted by restart, polling, cancellation, or retry. An ambiguous submission outcome pauses for reconciliation instead of automatically creating another potentially billable batch.
- Reuse the current database and server scheduler. Do not require a paid queue, hosted workflow service, new always-on worker, or subscription.
- Implementation targets current main, including the v2 `src/resume_pipeline.py`; do not restore the old local resume graph. Preserve unrelated local edits.
- Live paid-provider tests require an explicit bounded testing budget; ordinary automated tests use mocks.

## Review Focus

1. Credentials revoked while a batch is pending: pause with an actionable owner-only error; do not switch accounts or providers (Tasks 2, 5).
2. Schema-valid but factually unsupported output: use existing grounding validation and repair bounds before publication (Task 3).
3. Provider accepted submission but connection dropped: record submission uncertainty; never retry paid creation automatically (Task 5).
4. Profile/config/model changes while waiting: immutable non-secret snapshots preserve the originally selected inputs (Tasks 4, 5).
5. Two pollers or a crash during artifact publication: leases and unique item/application identity prevent duplicate submissions and outputs (Tasks 4, 5).

## File map

- `src/batch/types.py`: immutable request/result/state types and adapter protocol.
- `src/batch/capabilities.py`: explicit endpoint/model eligibility, limits, dated pricing.
- `src/batch/adapters/{openai,claude,gemini}.py`: provider transport and normalization only.
- `src/batch/requests.py`: shared pure request builders, extracted from existing generation functions.
- `src/batch/stages.py`: pure ready-work transitions for ranking, resume, letter, and answers.
- `src/batch/render.py`: existing local rendering and output publication from validated results.
- `server/batch_store.py`: durable leases, state transitions, owner scoping, idempotent publication.
- `server/batch_runs.py`: coordinator and owner-only batch action routes.
- `server/db.py`, new Alembic migration: additive batch tables and run mode/status fields.
- `server/runs.py`, `server/app.py`: mode dispatch, concurrency, existing scheduler integration.
- `web/components/batch-run-options.tsx`, `web/components/batch-run-progress.tsx`: opt-in controls and progress/actions.
- `web/lib/{api,types,cost-estimate,use-latest-runs}.ts`, run pages: typed client integration.
- Existing `src/{tailor,resume_pipeline,main,pipeline}.py`: minimal shared-builder/result seams, preserving immediate call traces.
- New tests named in each task, plus existing targeted suites and README usage documentation.

### Task 1: Pin ordinary-call billing behavior

**Files:** Create `tests/test_immediate_cost_invariants.py`; read `src/tailor.py`, `src/resume_pipeline.py`, `src/main.py`, `server/single_job.py` on current main.

**Interfaces:** Produces `RecordingProvider` test double implementing existing `LLMProvider` contracts, and deterministic successful/failing outputs for each existing stage.

- [ ] Capture committed-main expected call traces for ordinary ranking, resume planning/writing/repair, letter validation/critique/retry, answers, and single-job generation. Assertions compare provider/model, complete prompt/schema, reasoning settings, token limit, and call order; record fixtures before refactoring.
- [ ] Exercise cache hits and quota fallback traces; assert cache hits make zero generation calls and retries stay within existing bounds. Add mode tests expecting omitted mode to equal explicit `immediate` and batch-adapter construction count to be zero.
- [ ] Run `python -m pytest tests/test_immediate_cost_invariants.py -q`; baseline trace cases pass and new mode cases fail until Task 6. Commit baseline fixtures and tests without changing product behavior.

### Task 2: Provider batch transport and eligibility

**Files:** Create `src/batch/__init__.py`, `src/batch/types.py`, `src/batch/capabilities.py`, adapter files from the map, `tests/test_batch_adapters.py`, and documented JSON fixtures under `tests/fixtures/batch/`.

**Interfaces:** `BatchRequest(request_id: str, task: str, model: str, system: str, user: str, max_tokens: int, schema: dict | None, thinking: str, metadata: dict)`; `BatchResult(request_id: str, state: str, content: str | dict | None, usage: dict, error: str | None)`; `BatchStatus(provider_id: str, state: str, counts: dict)`; `BatchAdapter.submit(requests: list[BatchRequest], submission_key: str) -> str`, `.status(provider_id: str) -> BatchStatus`, `.results(provider_id: str) -> list[BatchResult]`, `.cancel(provider_id: str) -> None`. `get_batch_adapter(provider: str, credentials: dict) -> BatchAdapter`; `validate_batch_route(provider: str, endpoint: str, model: str) -> BatchCapability`.

- [ ] Write failing adapter tests: only official supported endpoint/model pairs pass validation; OpenAI-compatible resellers are rejected; requests retain model/schema/token/thinking parameters; shuffled results map by stable ID; per-item errors survive normalization; expired/cancelled jobs retain completed items. Revoked credentials yield a normalized auth error without fallback.
- [ ] Run `python -m pytest tests/test_batch_adapters.py -q`; confirm new imports/contracts fail.
- [ ] Re-fetch official provider batch/model documentation from the spec, verify SDK APIs and limit units, and implement the protocol using existing SDKs. Explicitly disable SDK automatic creation retries. Chunk requests by documented byte/count/token limits; reject oversize single requests before upload. Include input file cleanup and paginated result retrieval.
- [ ] Record supported models, endpoint, source URL, verification date, and pricing; unknown prices remain `None`. Never extrapolate support or price from a family name. Ensure optional adapter imports occur only in batch mode.
- [ ] Re-run adapter tests including chunk boundaries and SDK retry configuration; commit the independently usable adapter module.

### Task 3: Shared request seams and pure stage transitions

**Files:** Create `src/batch/requests.py`, `src/batch/stages.py`, `src/batch/render.py`, `tests/test_batch_stages.py`; modify existing generation files listed in the map only where sharing is necessary.

**Interfaces:** `StageState` is a versioned JSON-serializable application/run snapshot containing inputs, stage, bounded attempts, outputs, and errors. `prepare_ready_requests(state: StageState) -> list[BatchRequest]`; `consume_stage_results(state: StageState, results: list[BatchResult]) -> StageState`; `render_validated_application(state: StageState, output_dir: Path) -> dict`. These core functions import no server modules and cannot create provider clients.

- [ ] Write failing tests comparing prepared batch requests to Task 1 immediate fixtures, preserving ranking groups of 25 and current-main stage limits. Assert resume planning precedes writing, grounding failure precedes bounded repair, letter validation precedes bounded retry/critique, and completed/cache-hit items yield no requests.
- [ ] Add factually unsupported yet schema-valid resume fixtures; assert existing validation prevents publication. Assert provider failure remains a failed stage without synchronous fallback or artificial successful ranking scores.
- [ ] Run `python -m pytest tests/test_batch_stages.py -q`; confirm missing stage interfaces fail.
- [ ] Extract only shared pure prompt/parsing helpers; implement explicit stage transitions around current-main resume stages and existing letter/answer behavior. Store generated correction prompts after validated upstream output. Reject unknown state versions. Render only complete validated applications through current local writers, retaining current diagnostics/cache/tracker behavior.
- [ ] Run `python -m pytest tests/test_batch_stages.py tests/test_immediate_cost_invariants.py -q`; trace tests must still match; mode cases can remain deferred until Task 6. Commit shared seams and stage engine.

### Task 4: Durable owner-scoped state and leases

**Files:** Modify `server/db.py`; create `server/batch_store.py`, `server/migrations/versions/20261001_1200_f31b90eac672_batch_runs.py`, `tests/test_batch_store.py`.

**Interfaces:** `claim_due_batch(now: datetime, worker_id: str) -> BatchJob | None`; `record_submission(job_id: int, owner_id: int, provider_id: str) -> None`; `record_submission_unknown(job_id: int, owner_id: int, error: str) -> None`; `consume_results(job_id: int, owner_id: int, results: list[BatchResult]) -> None`; `publish_application_once(item_id: int, owner_id: int, artifact_manifest: dict) -> int`.

- [ ] Write failing tests for additive migration of an old database, default `immediate` run mode, owner scoping, unique request identity `(run_id, application_key, stage, attempt)`, and repeated publication returning the same Application row. Test simultaneous claimers and stale lease recovery without duplicate claims/submission.
- [ ] Run `python -m pytest tests/test_batch_store.py -q`; confirm missing persistence fails.
- [ ] Add tables for BatchJob and BatchItem and additive run fields. Job states: `prepared`, `submitting`, `submission_unknown`, `waiting`, `consuming`, `completed`, `partial_failed`, `failed`, `cancelled`. Persist lease owner/expiry, provider ID, input digest, polling timestamps, per-item usage and artifact references. Link migration to the latest main Alembic head at execution time; avoid multiple heads.
- [ ] Implement atomic conditional lease acquisition in existing SQL database, owner predicates for every operation, secret-free versioned input snapshots, and atomic staged-file publication with persisted manifest. Hold a per-user run reservation while releasing worker capacity when waiting. Enforce one application identity per batch run without changing immediate application persistence semantics.
- [ ] Run store tests including crash after file rename/before row commit and profile/config changes after snapshot; commit migration and persistence module.

### Task 5: Resumable coordinator, cancellation, and explicit recovery

**Files:** Create `server/batch_runs.py`, `tests/test_batch_coordinator.py`, `tests/test_batch_authz.py`; modify `server/app.py` to register protected routes and extend its existing scheduler.

**Interfaces:** `advance_batch_run(run_id: int, user_id: int) -> None`; `dispatch_due_batches() -> int`. Routes: `GET /api/runs/{run_id}/batch`, `POST /api/runs/{run_id}/batch/retry`, `POST /api/runs/{run_id}/batch/complete-now`, `POST /api/runs/{run_id}/batch/cancel`. Recovery POST bodies contain selected incomplete item IDs and a validated preview token.

- [ ] Write failing coordinator tests for restart with known provider ID, uncertain creation response, two pollers, completed result reuse, auth revocation, expired/cancelled partial outputs, and owner-only routes/artifacts. Assert zero automatic synchronous calls and zero re-creation after uncertainty.
- [ ] Run `python -m pytest tests/test_batch_coordinator.py tests/test_batch_authz.py -q`; confirm missing coordinator fails.
- [ ] Implement prepare/submit/poll/consume/render steps using Tasks 2–4. Persist `submitting` before network creation; crash or timeout without a saved provider ID becomes `submission_unknown`. Reconcile only using provider-supported metadata/search; if unresolved, pause and expose an actionable error. Never blind-resubmit.
- [ ] Use 60-second initial poll interval, exponential backoff capped at 15 minutes, and at most 120 scheduled status polls per provider batch; exceeding the ceiling pauses automatic polling without implying provider cancellation. Use existing scheduler, durable 120-second leases renewed during active work, bounded SDK timeouts, and no long-lived sleeping worker. Poll/read failures retry reads only.
- [ ] Implement owner-authenticated previews for retry and immediate completion, returning selected items, input digest, cost estimate or unknown, and expiry. Execution rechecks current item state and digest; never repeats completed work. Immediate completion uses existing task calls only after explicit confirmation. Cancellation stops new stages and retrieves already completed results where available.
- [ ] Run coordinator, authorization, store, and adapter tests; commit the resumable server workflow.

### Task 6: Opt-in run integration and ordinary-cost gate

**Files:** Modify `server/runs.py`, `server/cli.py` only if CLI mode is exposed, `src/pipeline.py` only for pure shared seams; create `tests/test_batch_run_modes.py`; finish Task 1 mode assertions.

**Interfaces:** `StartRunBody.execution_mode: Literal['immediate', 'batch'] = 'immediate'`; `StartRunBody.batch_routes` maps task name to explicit provider/model. `RunOut` includes execution mode and nullable batch summary. `run_pipeline` remains the immediate entry point; server dispatch chooses `advance_batch_run` only for batch runs.

- [ ] Write failing tests for omitted/explicit immediate mode producing identical traces, unsupported batch routes rejected before submission, scheduled mode persistence, waiting batches not consuming global active slots, and reservations preventing same-user output collisions. Test dry-run with no paid submissions.
- [ ] Run `python -m pytest tests/test_batch_run_modes.py tests/test_immediate_cost_invariants.py -q`; confirm only new mode requirements fail.
- [ ] Implement mode dispatch and eligibility validation, including every configured task needed by the selected quality tier. Do not instantiate a batch adapter for immediate mode. Preserve current immediate capacity/stop/scheduling behavior; track batch reservation separately from occupied active worker slots.
- [ ] Run run-mode and immediate trace tests plus `tests/test_run_concurrency.py`; all Task 1 tests now pass. Commit integration.

### Task 7: User controls, estimates, and end-to-end release

**Files:** Create components from the map and `web/lib/batch-run.ts`, `web/lib/batch-run.test.ts`; modify run pages, client types/API, cost estimates, and README. Add `tests/test_batch_end_to_end.py`.

**Interfaces:** `ExecutionMode = 'immediate' | 'batch'`; `BatchSummary` exposes state, provider/model groups, pending/succeeded/failed counts, estimates, and `next_poll_at`. Add typed clients for Task 5 previews/actions. `estimateBatchRun` returns nullable estimates for each route; it does not alter existing `estimateRun` results.

- [ ] Read `web/AGENTS.md` and relevant installed Next.js docs before edits. Write failing Vitest tests for immediate default, missing credentials, unsupported routes, unknown pricing, mode-specific estimates, and completed-item exclusion from recovery actions. Add mocked end-to-end tests from run creation through restart, shuffled results, dependent repair, publication, partial failure, and cancellation.
- [ ] Run `npm --prefix web test -- batch-run cost-estimate` and `python -m pytest tests/test_batch_end_to_end.py -q`; confirm new behavior fails.
- [ ] Implement immediate/batch selection, provider/model eligibility, per-round timing notice, waiting/partial status, explicit recovery preview/confirmation, cancellation billing notice, and unknown-cost display. Keep existing single-job and interactive controls on immediate paths. Update run lists and SSE/polling views for new states without continuous client polling when inactive.
- [ ] Run new Python batch tests and immediate invariants, existing provider/run/authz/config/resume tests relevant to touched code, then full backend suite once targeted checks pass. Run `npm --prefix web test`, lint affected files, and `npm --prefix web run build`. No live paid API calls.
- [ ] Inspect diff against current main, confirm unrelated local edits are absent, recheck migration heads, and verify ordinary trace fixtures remain identical. Commit UI/documentation; publish implementation branch and PR against current main with validation and remaining limitations. Link the implementation PR in final response; keep design PR distinct or update it clearly.

## Execution preparation and handoff

The spec is approved; this plan still needs user review. Recommend native execution because these tasks share stage/persistence contracts and the user's priority is avoiding additional cost. Once approved, create an isolated implementation workspace from latest main while preserving this dirty checkout, carry the approved spec/plan into it, and run a baseline before product edits. Follow the user's chosen execution method; do not dispatch agents without authorization.

Plan self-review: all spec sections are assigned above; the five Review Focus conditions have owner tasks and explicit tests. Stages use the same BatchRequest/BatchResult contracts throughout. The only deliberately pending work is user plan review and execution-method selection, not an unspecified product decision.
