---
title: "Watching what the on-call actually checks"
tags: [devtools, observability, full-stack, frontend, python, react, product]
role_fit: [swe, full-stack, devtools, product-engineer, platform-engineer]
company_fit: [startup, platform, devtools, enterprise]
one_liner: "Halved on-call triage time by encoding the three checks engineers always ran first instead of surfacing every metric."
---

Context: at Trellis Labs the on-call rotation was slow to first useful signal. Median was about eleven minutes from page to any idea of what was wrong. There was no shortage of dashboards; there were fourteen, and nobody could tell you which one to open.

What I did: before writing anything I sat with the two engineers who got paged most and watched them work three real incidents. Both of them, independently, ran the same three checks in the same order every time: recent deploys, error rate by service, and upstream dependency health. Everything else was situational. So I built one page that showed those three things and nothing else, in React over a FastAPI service, with a dependency view backed by a recursive Postgres query so you could see blast radius without opening more tabs.

What mattered: resisting the pull to make it comprehensive. Every reviewer wanted one more panel added, and each request was individually reasonable. I kept a list and shipped without them, then instrumented the dashboard itself and used the access logs to argue from data: the two panels I had conceded were opened four times in three weeks, and I removed them.

Outcome: median time to first useful signal dropped from eleven minutes to five across forty engineers. The lesson that stuck is that a tool competes with the habit it replaces, so the habit is the specification.
