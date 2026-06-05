---
title: ATS Optimization & Keyword Strategy
tags: [ats, keywords, skills, formatting, scan, applicant tracking]
role_fit: [swe, ml, data, sre, pm, ai]
applies_when: all roles — ATS scans every resume before a human reads it
---

## ATS Keyword Coverage

**Mirror the job description verbatim.** Copy exact tool names, framework versions, and skill phrases from the JD into skills and bullet points. ATS systems do exact-string matching — "React.js" and "ReactJS" are not the same token.

**Skills section is the primary ATS signal.** Applicant tracking systems weight skill tokens heavily. A sparse skills section (< 20 items) means many keywords score zero matches. Target 30+ skills across 5–6 groups to maximize coverage.

**Keyword placement hierarchy (highest to lowest ATS weight):**
1. Job title / headline
2. Skills section (each item is a discrete, scannable token)
3. Summary paragraph (first 3 sentences)
4. Bullet point opening (first 8 words of each bullet)

**Avoid burying keywords in prose.** "I used Python and SQL to build…" scores lower than a skills row that has "Python" and "SQL" as discrete tokens.

## Skills Section Construction

Group skills canonically — ATS systems recognize standard group headers:
- **Languages:** Python, Go, TypeScript, Java, C++, SQL, Bash
- **Frameworks & Libraries:** React, FastAPI, PyTorch, LangChain, Spring Boot
- **Data & ML:** scikit-learn, Pandas, Spark, dbt, Airflow, HuggingFace
- **Cloud & DevOps:** AWS, GCP, Azure, Docker, Kubernetes, Terraform, CI/CD
- **Databases:** PostgreSQL, MongoDB, Redis, BigQuery, Snowflake
- **Tools & Platforms:** Git, Jira, Figma, Grafana, Prometheus

**Minimum 25 skill items.** Anything below 20 leaves significant ATS budget unused. Do not pad with soft skills (communication, leadership) — ATS systems ignore them and they waste token budget.

**Canonical names matter.** Use "PyTorch" not "pytorch", "LangChain" not "langchain", "REST APIs" not "REST". Match the capitalisation used in the JD.

## Formatting Rules for ATS Compatibility

- Use standard section headers: "Experience", "Education", "Skills", "Projects" — not creative alternatives like "Where I've Worked"
- No tables, text boxes, or columns for core content — many parsers fail on these
- Dates in MM/YYYY or Month YYYY format — "Jan 2024 – May 2024" is safer than "2024"
- Company name before title (standard order most ATS parsers expect)
- Action verb + metric in bullets — ATS keyword extractors look for verb-noun pairs
