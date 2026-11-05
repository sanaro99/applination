# Execution ledger - plan: docs/superpowers/plans/2026-10-01-discounted-bulk-runs.md

Base: 8aa46d0, current main at implementation start. Native execution approved.

Pre-flight: adapters produce provider-normalized results, transcript keys identify requests, workflow consumes content through existing Tailor methods, server store owns leases and snapshots. Shared interfaces align.

Ruling: reuse existing generation methods through a network-free replay provider instead of extracting every prompt builder or duplicating stage logic. Each independent operation runs to its next pending AI call, and successful responses are replayed from its immutable transcript. This avoids prompt/validation drift and keeps all ordinary generation code unchanged. Cost if wrong: an unstable identity could create extra requests; tests pin payload and identity stability.

Ruling: persist BatchJob rows and one owner-scoped JSON transcript per run, keyed by unique request SHA-256, instead of a separate BatchItem row per request. A single durable renewable run lease serializes modifications. This removes cross-table consumption races without sacrificing stable per-item states, usage, or explicit recovery selection. Cost if wrong: large snapshots need more DB storage; bulk generation is currently capped at 30 selected jobs.

Ruling: adapters share a focused module rather than one file per provider; they normalize a common transport while provider branches remain explicit. No immediate SDK calls were modified.

Verification: baseline run-concurrency and demo suites: 40 passed. New adapter/replay tests first failed with missing batch module, then 9 passed; the deferred immediate mode test remained red until run dispatch integration. Persistence tests first failed with missing models, then 2 passed. Coordinator tests first failed with missing module; a mistaken test import was corrected after reading its traceback. Integrated new batch tests, ordinary ranking/mode checks and existing concurrency suite: 27 passed.

Tasks 1-7 implemented. Immediate generation modules (`src/main.py`, `src/tailor.py`, `src/resume_pipeline.py`, and every existing provider) are byte-for-byte unchanged from main. Ordinary dispatch never constructs a batch adapter; default-mode, ranking budgets, cache/concurrency behavior, and existing single-job/provider coverage are exercised by the backend suite.

Review: one fresh read-only final reviewer identified stale-worker submission and publication races, recovery lease expiry, unresolvable cancellation, missing-key uncertainty, semantic recovery selection, and GPT-4.1 incompatibility. Fixes fence submission in a lease/job transaction, add a unique nullable batch publication identity and insertion lease check, renew recovery leases, allow explicit abandonment, initialize providers before the paid boundary, and preserve failed validation usage. GPT-4.1 routes are withheld because existing ordinary recovery cannot send a compatible payload. Scheduled and pre-snapshot cancellations complete without fetching or calling providers. The same reviewer verified the fixes; no second reviewer seat or paid tests were used.

Additional regression: a closed SSE event loop originally paused a successfully persisted tick. A forced closed-loop end-to-end test failed, then passed after making notifications non-authoritative. The end-to-end test uses real generation validators and document rendering, reversed native result identities, repeated durable ticks, and duplicate publication/submission assertions.

Creation crash consistency: fault injection at BatchRunState insertion exposed an orphan Run row, because creation used two commits. Run and state now commit together; immediate creation retains its single commit. The fault-injection test asserts rollback leaves no orphan run.

Verification: final full backend suite: 740 passed. After the creation transaction fix, 30 targeted run, concurrency, recovery, authorization and ownership-lint checks also passed. Earlier checks included 9 store/coordinator regressions, 16 authorization/replay/run-mode checks, and 7 end-to-end/coordinator checks after the SSE fix. Frontend: 39 tests passed, affected-file ESLint passed, production webpack build passed with TypeScript checking. Migrations are applied to fresh databases by the tests. Git diff whitespace checks passed, and origin/main remained 8aa46d0 at the publishing check.

Release boundaries: native protocols are tested with SDK fixtures and mocks. No live paid provider requests, production deployment, or merging are included. The existing server must stay available to poll asynchronous results; unknown prices remain unknown, and unresolved submissions may still be billed after explicit local abandonment.
