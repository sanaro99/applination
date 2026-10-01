# Discounted bulk application runs

Status: proposed architecture; awaiting written-spec review before implementation.

## Intent and accepted constraints

Reduce the AI cost of preparing multiple job applications using providers' discounted asynchronous batch APIs. The user approved an opt-in overnight mode supporting OpenAI, Claude, and Gemini, with persistent progress and explicit full-price fallback. The user additionally requires that the architecture must not increase the cost of existing ordinary calls or ordinary single-application preparation.

Success means eligible requests use the actual provider batch endpoint and its discounted billing, while ordinary runs retain their existing billable behavior. Discounted AI generation does not discount other services or submit applications to employers.

## Cost invariants

- Existing runs and single-job actions default to immediate mode. Existing saved configurations need no changes.
- Immediate mode retains provider selection, per-task model overrides, prompts, schemas, reasoning settings, token limits, cache behavior, quality checks, and retry limits. It must not initialize batch adapters, submit batch requests, poll batches, or make additional AI calls.
- Selecting a batch model never changes the model used for ordinary calls. New OpenAI support is additive; existing configured providers keep their routes.
- Batch mode cannot silently promote a model, increase a token budget, add an AI planning step, or fall back to synchronous paid generation.
- A failed or expired batch item remains failed or pending user action. A separate explicit action can request discounted retry or full-price immediate completion, with an estimate and affected items shown first.
- Completed items are never resubmitted by restart, polling, cancellation, or retry. An ambiguous submission outcome pauses for reconciliation instead of automatically creating another potentially billable batch.
- The guarantee concerns changes introduced by this feature, not external price changes or natural variability in generated token counts. Estimates are not provider invoices.
- Reuse the current database and server scheduler. Do not require a paid queue, hosted workflow service, new always-on worker, or subscription. Batch storage and status polling consume some existing host resources; only opted-in batch runs incur this work, and polling must be bounded.

## Existing architecture

`src/pipeline.py` fetches and ranks jobs, checks the application cache, then calls `process_job` sequentially for each selected job. `src/tailor.py` already combines up to 25 job postings into ordinary ranking requests. That prompt grouping does not enable batch billing.

Resume preparation in `src/tailor_graph.py` has dependent stages: generation, local keyword audit, optional correction, critique, revision, and line fitting. Cover letters also have validation and bounded correction. Batching dependent stages requires several rounds and may exceed one overnight window.

`server/runs.py` manages queued/running jobs and per-user concurrency. `server/db.py` stores runs, ranked jobs, and applications. The core pipeline must continue to avoid importing server modules.

The checkout has unrelated local changes, including pipeline, provider, database, and run files. Implementation must use current main as its base and preserve those changes; review any relevant differences rather than publishing them as part of this feature.

## Alternatives and selected approach

1. Merely parallelize existing calls: improves speed but does not activate discounted pricing.
2. Replace all provider calls with a blocking batch wrapper: superficially simple, but ties up workers, makes restart unsafe, and can introduce a waiting period at every dependent call.
3. Add a separate persisted batch coordinator for opted-in runs: selected. Ordinary execution remains the existing pipeline; batch execution groups ready requests by provider, credential owner, model, and stage, and resumes from recorded results.

## Run modes and user experience

The run request gains an execution mode with `immediate` as its default and `batch` as an explicit selection. The UI presents immediate mode and a lower-cost asynchronous mode, listing eligible providers/models and explaining that each batch round can take up to 24 hours. The final end-to-end run can take longer when dependent rounds are necessary.

Batch selection uses the user's existing credentials. Eligibility is specific to provider endpoint and model, not inferred from an OpenAI-compatible URL or a model name on a reseller. Unsupported routes fail validation before paid submission. Models and prices come from verified provider capability/pricing data with a recorded date; unknown prices display as unknown.

Progress distinguishes preparing, submitting, waiting, consuming results, rendering, partially failed, completed, and cancelled. Completed application materials remain available when other items fail. The UI reports processed/failed/pending counts and estimated eligible savings. Batch mode does not change employer submission or Gmail behavior.

## Provider boundary

Introduce an independent batch interface for capability checks, request preparation, submission, status retrieval, result retrieval, and cancellation. Implement OpenAI Batch, Anthropic Message Batches, and Gemini Batch adapters. Each normalizes provider state and per-item errors but preserves provider usage details.

Batch request preparation must reuse the same deterministic prompt construction, schema, response parsing, and validation as immediate generation. Extract shared pure helpers only where necessary, with immediate-call equivalence tests. Keep existing `text_call` and `json_call` contracts unchanged.

Each request has a stable application/stage/attempt identifier. Result association uses that identifier, never response order. Respect provider request count, file-size, token-queue, and model constraints, splitting batches without changing prompts. Disable automatic submission retries unless provider idempotency is explicitly supported and verified.

## Persistence and recovery

Add additive migrations for the run mode, durable batch jobs, and batch items. Batch jobs record owner, run, provider/model, stage, submission state, provider identifier, input digest, timestamps, polling schedule, lease, and errors. Items record stable request identity, application identity, attempt, state, usage, and artifact references. Use uniqueness constraints to prevent duplicate consumption and duplicate output publication.

Store immutable run inputs and request/result artifacts under the user's run directory with existing access boundaries. Store no API keys in artifacts, logs, or batch records. Resolve credentials from the user's existing secret storage. Changes to profile/config after submission cannot silently alter pending inputs.

The server coordinator claims work using durable leases and performs short units of work. Waiting batches release active worker capacity. Existing per-user output ownership still applies; a waiting run retains a reservation so another run cannot write the same artifacts. Immediate runs for other users remain schedulable.

After restart, recover leases and resume known provider jobs rather than resubmitting. If the server lost the submission response, use provider metadata/status reconciliation where supported; otherwise expose the uncertainty for explicit resolution. Network errors while polling or retrieving results only retry retrieval, with backoff and a configured polling ceiling.

Consume and validate results transactionally, then render with the current local document generation. Artifact publication and application-row creation must be idempotent across crashes. Persist per-item failures; retrieve completed outputs even when a provider job expires or is cancelled.

## Stage scheduling and quality

Keep existing ranking prompt grouping and offer discounted execution for its prepared requests. After ranking and selection, skip cache hits before submission. Prepare initial resume, cover-letter, and application-answer requests across selected jobs where their inputs are ready.

After receiving results, apply current local audits and validators. Prepare dependent correction/critique/revision requests in subsequent discounted rounds, maintaining the existing attempt bounds and quality gates. Do not remove checks merely to claim faster or cheaper completion. A dependent request is submitted only after its upstream result is validated.

Interactive corrections remain immediate when the user explicitly invokes an existing interactive action. Resuming a batch never invokes that action automatically. Cancellation stops new submissions, requests provider cancellation where supported, and makes clear that already processed requests may still be billed.

## Validation and release

- Compare mocked provider call traces for ordinary bulk and single-job flows before/after the change: same call counts, request payloads, models, token limits, retries, and cache hits. Assert no batch client is constructed in immediate mode.
- Test all adapters against documented payload/result fixtures, including unordered output, failed items, expiration, cancellation, malformed JSON, and unsupported models.
- Exercise restart before/after submission and output publication, uncertain submission outcomes, duplicate pollers, stale leases, and repeated result consumption. Verify no automatic duplicate paid submission.
- Test ownership of every batch route, stored artifact, and credential lookup; test concurrency reservations and that waiting batches release worker slots.
- Verify dependent stages retain validators and retry bounds, no full-price fallback occurs automatically, and explicit completion affects only selected incomplete items.
- Test UI defaults, old configurations, status display, partial completion, and unknown pricing. Live paid-provider tests require an explicit bounded testing budget; ordinary automated tests use mocks.
- Release as opt-in on a branch with a PR against current main. Review the written implementation plan before product code changes. No required infrastructure migration to a paid service.

## Official references checked during design

- OpenAI GPT-6 Luna: https://developers.openai.com/api/docs/models/gpt-6-luna
- OpenAI Batch: https://developers.openai.com/api/docs/guides/batch
- Claude batches: https://platform.claude.com/docs/en/build-with-claude/batch-processing
- Gemini Batch: https://ai.google.dev/gemini-api/docs/batch-api

These sources establish 50% batch pricing for eligible usage, with asynchronous turnaround. Eligibility and prices must be revalidated during adapter implementation; the entire application workflow is not guaranteed to cost half as much or finish within a single batch window.
