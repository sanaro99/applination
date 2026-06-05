# Stories Index

Each `*.md` file in this folder is one story from my background. The
cover-letter builder matches job descriptions against the `tags` in the
frontmatter and picks the 1–2 most relevant stories per letter.

## Writing a new story

Copy an existing file. Keep the frontmatter structure:

```yaml
---
title: "Short descriptive name"
tags: [lowercase, hyphenated, specific]
role_fit: [swe, ml-engineer, sre, ...]   # types of roles this story speaks to
company_fit: [finance, startup, platform, ...]   # types of companies
one_liner: "Single sentence the tailor can quote as a hook"
---
```

Body structure that works well:
- **Context**: what was the problem / setup / motivation
- **What I did**: the actual work (specific, not generic)
- **What mattered**: the hard or interesting part — the thing that shows judgment
- **Outcome**: results, but also what you learned

Keep stories around 200–300 words. The tailor reads the full body, so don't
over-edit — texture and specifics are what make cover letters not sound like
every other cover letter.

## Tag taxonomy (expand as needed)

**Technical areas:** ai, llm, rag, ml, nlp, systems, infrastructure, networking,
sre, reliability, observability, full-stack, frontend, backend, data, platform,
devtools, security, accessibility, ethics

**Specific tech:** python, typescript, react, nextjs, fastapi, langgraph,
pytorch, postgresql, redis, docker, kubernetes, azure, aws, linux

**Role types (role_fit):** swe, ml-engineer, ai-engineer, sre, platform-engineer,
full-stack, frontend, backend, product-engineer, research, devtools, teaching

**Company types (company_fit):** finance, startup, bigtech, enterprise,
ai-first, platform, consumer, accessibility, mission-driven, infrastructure

## Current stories

- **autoflow** — LLM-powered automation platform (AI, LangGraph, finance)
- **rag-chatbot** — RAG over team email for on-call (AI, RAG, SRE)
- **ubs-sre** — Running incident response for $10B/day systems (SRE, reliability)
- **monitoring-dashboard** — Config-driven dashboard for 30+ teams (platform, devtools)
- **private-cloud** — Cross-continent self-hosted cloud (infra, systems, curiosity)
- **genasl** — AI-generated sign language overlays (AI, accessibility, ethics)
- **darkguard** — Browser extension for dark patterns (ethics, UX, consumer)
- **fantasy-cricket** — Full-stack app with 1K users (full-stack, product)
- **mentorship** — Teaching + mentoring story (people, feedback, inclusion)
