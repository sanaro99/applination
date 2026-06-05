---
title: JD Reading Strategy — Extracting Signal Before Tailoring
tags: [jd-reading, matching, strategy, role-detection, keywords]
role_fit: [swe, ml, ai, data, sre, pm, intern]
applies_when: every tailoring run
---

## Read the JD in This Order

1. **Title + first 200 chars** → role category (SWE / ML / SRE / Data / PM).
2. **"Responsibilities" or "What you'll do" section** → the actual work.
3. **"Requirements" / "Qualifications"** → hard skills + scope hints.
4. **Company description** → domain context for the cover letter hook.

Ignore the boilerplate "we're a fast-paced company" intros. They rarely
contain matchable signal.

## Detect the Role Category Fast

| Title contains | Likely category |
| --- | --- |
| Software Engineer, SWE, Backend, Full-Stack, Developer | swe |
| Machine Learning, ML, AI, Applied Scientist, NLP, CV | ml |
| Data Scientist, Data Engineer, Analytics | data |
| SRE, Site Reliability, DevOps, Platform, Infrastructure | sre |
| Product Manager, PM, Associate Product | pm |

When the title is ambiguous ("Solutions Engineer"), use the JD body to
disambiguate: customer-facing language → solutions, pipeline language → SWE.

## Extract Hard Skills vs Soft Skills

**Hard skills** (ATS keywords — match verbatim where truthful):
- Languages: Python, Java, Go, JavaScript, SQL
- Frameworks: React, Django, FastAPI, PyTorch
- Cloud: AWS, GCP, Azure, Kubernetes, Docker
- Domain tools: Snowflake, Kafka, Spark, Airflow

**Soft skills** (do NOT mirror verbatim — they're filler):
- "Strong communication", "team player", "fast-paced environment"
- "Self-starter", "growth mindset", "ownership"

Hard skills go in the Skills section. Don't pad the Skills section with
soft skills — recruiters notice.

## Map Strengths to JD Pain Points (Not Just Keywords)

Keyword matching is necessary but not sufficient. A good tailored resume
addresses what the role exists to *solve*, not just what the JD lists.

**Examples:**
- JD says "build MLOps tooling to power teams across the company" →
  highlight prior LLM tooling work (AutoFlow), not just "PyTorch".
- JD says "scale our data pipeline 10x" → highlight scale metrics ($10B+
  daily transactions) even if Spark isn't mentioned in JD.
- JD says "improve developer productivity" → highlight tools you built that
  shipped, not classroom projects.

## When the JD Is Sparse (Common from SimplifyJobs / Lever / Ashby)

Many jobs ship with only a title and company name. In this case:
- **Don't fabricate JD specifics.** "I saw your team builds X" rings false
  when X isn't in the JD.
- **Use the company's domain as the anchor.** "Cloudflare engineering teams
  often have to ship AI features without their own ML platform — I built
  one at UBS that 20 teams use daily."
- **Lean harder on candidate strengths.** The JD didn't give you a hook;
  give yourself one.

## Surface Transferable Skills (Not Just Domain Matches)

If the JD asks for ML but the candidate is mostly SWE:
- Lead with the most ML-adjacent project (RAG chatbot, AutoFlow with
  LangGraph) and bring it to the summary opening.
- Don't oversell — labeling the candidate "ML Engineer" when the work is
  90% SWE will fail an interview screen.
- Frame strengths as building blocks: "production-grade LLM systems" is
  truthful for someone who shipped a RAG chatbot; "trained foundation
  models from scratch" is not.

## Quick Checklist Before Generating

- [ ] Role category identified (one of swe / ml / data / sre / pm)
- [ ] 6–10 hard-skill keywords extracted for the Skills section
- [ ] One JD pain point identified for the summary opening to address
- [ ] Strongest matching project chosen (it goes first)
- [ ] If JD is sparse, decided on the company-domain anchor for cover letter
