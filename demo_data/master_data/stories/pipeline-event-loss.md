---
title: "The 4% that nobody saw"
tags: [data, infrastructure, reliability, observability, python, kafka, debugging]
role_fit: [swe, backend, platform-engineer, sre]
company_fit: [platform, infrastructure, startup, bigtech]
one_liner: "Found a silent 4% event loss that had run for eight months because the retry logic disguised it as ordinary load."
---

Context: I joined Northwind Analytics as a data platform intern and inherited a Kafka-backed batch pipeline that everyone described as fine. It was not fine. A reconciliation script I wrote in my first week to learn the schema kept coming up short against the upstream source, by about 4%, consistently, going back at least eight months.

What I did: I spent two weeks reading the retry path rather than adding instrumentation, which in hindsight was backwards. The bug was that a failed write was re-enqueued onto the same partition that had failed it, so a partition that fell behind became a partition that dropped. The graphs looked like normal load because every drop was recorded as a retry, and retries were expected.

What mattered: the fix took an afternoon. Retries moved to a dedicated queue with exponential backoff. Loss went from 4% to under 0.1% and throughput rose about 30%, because the pipeline stopped fighting itself. But the part I argue for now is the alerting I added afterwards, on freshness and drop rate, which would have surfaced this in a day. The real defect was not the retry logic. It was that nothing was watching, and a system nobody is watching will keep any secret you let it keep.

Outcome: I backfilled fourteen months of affected records with an idempotent Airflow DAG and wrote the runbook the on-call rotation still uses. I also stopped accepting "it looks fine" as a statement about a system.
