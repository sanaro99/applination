---
title: Role-Specific Tailoring — ML, SWE, SRE, Data, PM
tags: [ml, swe, sre, pm, data, ai, role, tailoring, prioritization]
role_fit: [swe, ml, data, sre, pm, ai]
applies_when: choosing which experience and projects to emphasize per role type
---

## ML / AI / Research Engineer Roles

**What recruiters look for:** End-to-end model ownership, not just "used sklearn."

**Lead with:**
- Model type + framework: "Transformer-based sequence classifier (PyTorch + HuggingFace)"
- Training pipeline: data preprocessing → training → evaluation → deployment
- Quantitative results: accuracy delta, latency improvement, throughput
- If LLM work: prompt engineering, RAG retrieval, fine-tuning, RLHF, eval harness

**Skills to surface first:** PyTorch, TensorFlow, HuggingFace Transformers, LangChain, scikit-learn, CUDA, ONNX, MLflow, Weights & Biases, RAG, vector databases (Pinecone, Weaviate, pgvector)

**Project prioritization:** Rank projects with real models trained > demos wrapping APIs > pure data analysis

**Bullet anti-patterns to avoid:**
- "Used machine learning to predict X" — no model type, no metric
- "Implemented neural network" — too vague; name the architecture

## Software Engineering (SWE) Roles

**What recruiters look for:** Systems thinking, production impact, and code quality signals.

**Lead with:**
- Scale: users served, requests/second, data volume
- System design decisions: why this architecture, what tradeoffs
- End-to-end ownership: "designed, built, and deployed"

**Skills to surface first:** Primary language matching JD, REST APIs, system design, databases (PostgreSQL, Redis), concurrency, testing frameworks, CI/CD

**Project prioritization:** Deployed / live projects > hackathon winners > coursework projects with notable scope

**Bullet anti-patterns to avoid:**
- "Worked on backend API" — what specifically? what was the impact?
- "Helped with" — avoid; own your contribution directly

## SRE / DevOps / Platform Engineering Roles

**What recruiters look for:** Reliability metrics, automation ratio, incident response ownership.

**Lead with:**
- SLOs/SLAs you owned or improved
- Toil you automated (hours saved)
- On-call improvements: MTTR reduction, alert noise reduction, runbook coverage
- Infrastructure scale: nodes managed, services owned

**Skills to surface first:** Kubernetes, Terraform, Prometheus, Grafana, AWS/GCP/Azure, Ansible, Helm, Docker, CI/CD (GitHub Actions, Jenkins, ArgoCD), observability stack

**Reliability metric formulas:**
- "Improved availability from X% to Y%" (e.g., 99.5% → 99.97%)
- "Reduced MTTR from Xh to Ymin"
- "Automated Z% of on-call runbooks, eliminating N pages/week"

**Project prioritization:** Infrastructure automation > monitoring/alerting setup > scripts that replaced manual work

## Data Engineering / Analytics Roles

**What recruiters look for:** Pipeline reliability, data scale, and business impact of insights.

**Lead with:**
- Data volume: events/day, GB/TB processed
- Pipeline SLA: "< 1% SLA breach", "99.9% uptime"
- Business impact: "enabled $2M revenue analysis", "reduced reporting latency from 24h to 1h"

**Skills to surface first:** SQL, Python, Spark, dbt, Airflow, Kafka, Snowflake, BigQuery, Redshift, Looker/Tableau, data modeling, ETL/ELT

**Bullet pattern:** `[Pipeline type] ingesting [volume] from [N sources] with [SLA/reliability metric], enabling [business outcome].`

## Product Management Roles

**What recruiters look for:** Shipped products with measurable user/business impact, cross-functional leadership, data-driven decisions.

**Lead with:**
- Feature shipped + outcome: "launched X, drove Y% increase in DAU"
- Who you aligned: "aligned 3 engineering teams and legal to ship in 6 weeks"
- Metric you owned: "owned checkout conversion rate; improved from 3.2% to 4.1%"

**Skills to surface first:** Product discovery, A/B testing, SQL (for self-serve data analysis), roadmap prioritization, user research, Jira/Linear, Figma (collaboration)

**Avoid on a PM resume:** Deep technical implementation details — mention you worked with engineering but focus on outcome and decision-making, not the code.

**Project prioritization:** Products with real users > hackathon apps you defined the roadmap for > academic projects

## Ordering Experience / Projects for Each Role

When space is limited, reorder to put the most relevant entry first:
- ML role → ML project first, even if it's shorter than a SWE experience
- SRE role → infrastructure automation or on-call experience first
- PM role → any product ownership first; de-emphasize pure coding projects

Always match the most prominent role experience to the JD's primary requirement.
