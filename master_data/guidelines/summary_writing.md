---
title: Summary / Headline Writing — Identity, Keywords, Flagship Metrics
tags: [summary, identity, headline, keywords, metrics, swe, ml, sre, pm, data, ai]
role_fit: [swe, ml, data, sre, pm, ai]
applies_when: summary section — first thing recruiter and ATS read
---

## Summary Section Purpose

The summary is the only free-form text recruiters read in the first 6 seconds. It must:
1. Establish your identity (what KIND of engineer you are)
2. Mirror 3–5 keywords from the JD
3. Drop one flagship metric that proves you build things that work at scale

The summary is NOT a sentence like "Motivated CS student seeking opportunities." It is a value proposition.

## Identity-First Opening

Start with your role identity, not your name (the header already has that) and not generic phrases.

**Weak:** "A passionate software engineer with experience in many technologies..."
**Strong:** "ML Infrastructure engineer with experience shipping LLM-powered pipelines end-to-end — from prompt engineering and RAG retrieval to latency-optimized serving."

**Pattern:** `[Role identity] with [scope/scale] — [flagship skill or project that proves it].`

For ML/AI roles: lead with model type, framework (PyTorch / HuggingFace / LangChain), and deployment context.
For SWE roles: lead with system type (distributed systems, APIs, frontend-to-backend) and scale.
For Data roles: lead with pipeline scope, data volume, and tooling (Spark, dbt, Airflow).
For PM roles: lead with product domain and a shipped outcome, not generic "cross-functional leadership."
For SRE roles: lead with reliability work — SLOs, incident response, automation ratio.

## Keyword Mirroring

Scan the JD for the 3–5 most distinctive technical terms (not generic words like "collaborate" or "agile"). Place those exact strings in the summary.

If the JD says "LLM fine-tuning, RLHF, and model evaluation" → your summary should contain "LLM fine-tuning" and "RLHF" or "reinforcement learning from human feedback."

If the JD says "Kubernetes, Terraform, and CI/CD" → your summary should mention at least two of those.

## Flagship Metric Placement

Include one concrete number in the summary. Recruiters scan for this as a credibility signal.

**Examples by role:**
- SWE: "reduced API p99 latency from 420ms to 85ms" or "served 50K daily active users"
- ML: "cut false-positive rate from 18% to 3%" or "4× faster inference via ONNX quantization"
- Data: "ingested 2M+ events/day with < 1% SLA breach rate"
- SRE: "improved system availability from 99.5% to 99.97%" or "reduced MTTR by 60%"
- PM: "drove 23% DAU growth over one quarter"

## Length Constraint

Summary must be ≤ 400 characters (roughly 2–3 sentences). Recruiters do not read long paragraphs. Every word must earn its space.

**Checklist:**
- [ ] Starts with role identity (not "I am" or generic opener)
- [ ] Contains 3–5 JD keywords verbatim
- [ ] Includes at least one metric or concrete outcome
- [ ] ≤ 400 characters
- [ ] No soft-skill filler ("passionate", "dedicated", "hard-working")
