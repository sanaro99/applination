---
title: Bullet Writing — PAR Format, Line-Fill, Quantification
tags: [bullets, writing, quantification, par, line-fill, action verbs, impact]
role_fit: [swe, ml, data, sre, pm, ai]
applies_when: all experience and project bullets
---

## PAR Format (Problem → Action → Result)

Every bullet should answer three questions:
1. **Problem/Context** (optional, brief) — what situation or constraint existed?
2. **Action** — what did YOU specifically do? (start with a strong past-tense verb)
3. **Result** — what measurable outcome happened?

**Template:** `[Verb] [what you built/did] [using what] [that achieved/reducing/improving] [metric]`

**Weak (action only):** "Built a data pipeline using Apache Airflow."
**Strong (PAR):** "Engineered Airflow DAG ingesting 2M daily events from 6 upstream APIs, cutting SLA breach rate from 12% to < 1% and saving 4 hours/week of manual triage."

## Line-Fill Rule

A bullet that ends partway across a line wastes horizontal space and signals
laziness. Every bullet must visually fill **one complete line** OR **two
complete lines** — never a half-line stub or a forbidden mid-zone wrap.

The page renders at 10pt Times New Roman with 0.25" L/R margins, so each
printed line holds roughly **132 characters**. (The authoritative, font-aware
bands live in `src/line_fitter.py::configure_for_font`; the numbers below are
the 10pt values.)

**Allowed bands (anything outside is a failure):**
- **Single-line:** **116–125 characters** — packs the line nearly edge-to-edge
  (≥~88% full). Do NOT stop short at ~90–110; that leaves the line visibly
  under-filled.
- **Double-line:** **205–258 characters** — wraps to two lines, line 2 at least
  ~55% full. Visually packed without spilling to a third line.

**FORBIDDEN zone:** **126–204 characters** — wraps to a second line that stays
mostly empty. The post-LLM `line_fitter` swaps in a longer master variant if
one matches; if none fits, the bullet is left INTACT (never truncated) — broken
sentences are worse than wrap waste.

**Also avoid:** below ~79 characters (the single line ends well short), and the
**under-filled single** range ~79–115 (renders on one line but wastes the right
third). Expand these toward 116–125 using the technique below.

**How to expand a short bullet:**
- Add the missing PAR component (usually the Result)
- Specify the scale/scope: "across 3 microservices", "for a team of 8 engineers", "serving 50K daily users"
- Add the tech stack used: "using Python + PostgreSQL + Redis"
- Quantify what was previously vague: "reduced latency" → "reduced p99 latency from 420ms to 85ms"

## Action Verb Variety

Never repeat the same verb twice in the same section. Rotate through:

**Built / Engineered:** Engineered, Architected, Implemented, Developed, Designed, Built, Deployed, Shipped

**Improved / Optimized:** Reduced, Optimized, Accelerated, Cut, Halved, Improved, Boosted, Streamlined

**Led / Owned:** Led, Owned, Drove, Spearheaded, Coordinated, Managed, Delivered

**Analyzed / Researched:** Analyzed, Investigated, Modeled, Evaluated, Benchmarked, Profiled, Diagnosed

**Automated / Integrated:** Automated, Integrated, Migrated, Refactored, Unified, Consolidated, Standardized

## Quantification Rules

- **Always prefer exact numbers over words:** "3x faster" beats "significantly faster"
- **Use relative + absolute when both are meaningful:** "reduced cost by 60% ($12K/month)"
- **Scope matters:** "served 50K daily active users", "across 8 microservices", "for a 12-engineer team"
- **Estimate is OK:** "~40% reduction" is better than no number at all; use "~" to signal estimate
- **Time saved:** Convert to hours/week or engineer-days — "saved 6 hours/week of manual review"
- **Avoid vague intensifiers:** "significantly", "greatly", "dramatically" — replace with a number

## Project Bullets Specifically

Project bullets need the same rigor as experience bullets. Common failure mode: "Built X using Y" with no result.

Always include at least one of:
- Users or adoption: "used by 200+ students at UW"
- Performance: "inference in < 50ms on CPU"
- Scale: "processes 10K requests/day"
- Outcome: "reduced false-positive rate from 18% to 3%"
- Recognition: "won 1st place at UW Hackathon (120 teams)"
