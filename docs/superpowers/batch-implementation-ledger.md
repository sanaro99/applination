# Execution ledger - plan: docs/superpowers/plans/2026-10-01-discounted-bulk-runs.md

Base: 8aa46d0, current main at implementation start. Native execution approved.

Pre-flight: adapters produce provider-normalized results, transcript keys identify requests, workflow consumes content through existing Tailor methods, server store owns leases and snapshots. Shared interfaces align.

Ruling: reuse existing generation methods through a network-free replay provider instead of extracting every prompt builder or duplicating stage logic. Each independent operation runs to its next pending AI call, and successful responses are replayed from its immutable transcript. This avoids prompt/validation drift and keeps all ordinary generation code unchanged. Cost if wrong: an unstable identity could create extra requests; tests pin payload and identity stability.

Ruling: persist BatchJob rows and one owner-scoped JSON transcript per run, keyed by unique request SHA-256, instead of a separate BatchItem row per request. A single durable renewable run lease serializes modifications. This removes cross-table consumption races without sacrificing stable per-item states, usage, or explicit recovery selection. Cost if wrong: large snapshots need more DB storage; bulk generation is currently capped at 30 selected jobs.

Ruling: adapters share a focused module rather than one file per provider; they normalize a common transport while provider branches remain explicit. No immediate SDK calls were modified.

Verification: baseline run-concurrency and demo suites: 40 passed. New adapter/replay tests first failed with missing batch module, then 9 passed; the deferred immediate mode test remained red until run dispatch integration. Persistence tests first failed with missing models, then 2 passed. Coordinator tests first failed with missing module; a mistaken test import was corrected after reading its traceback. Integrated new batch tests, ordinary ranking/mode checks and existing concurrency suite: 27 passed.

Task 1: ordinary ranking/token-budget and default-mode checks implemented; broader trace equivalence is pending.
Tasks 2-4: adapter, replay workflow, migrations and leases implemented; additional protocol/recovery edge checks pending.
Tasks 5-6: server coordinator and opt-in dispatch implemented; authorization and end-to-end verification pending.
Task 7: UI and release verification pending.
