---
title: Metric Truthfulness — How to Quantify Without Lying
tags: [metrics, truthfulness, par, anti-fabrication, quantification]
role_fit: [swe, ml, ai, data, sre, pm]
applies_when: any bullet that ends without a number
---

## The Recruiter Test

A bullet that says "improved performance" reads like a placeholder. One that
says "cut p99 latency from 420ms to 85ms" reads like work that actually
shipped. The difference is signal, not vocabulary.

## Red-Flag Vague Verbs

These signal that no metric exists and the writer tried to dress it up:
- "significantly", "substantially", "dramatically", "notably"
- "leveraged" (instead of "used" + the concrete outcome)
- "spearheaded", "drove", "owned" — fine on their own, but red flag when
  paired with no number
- "best-in-class", "industry-leading", "cutting-edge" — never use

## How to Quantify Without Fabricating

**Tier 1 (best):** Exact pre/post metric.
- "Reduced average build time from 12 min to 4 min"
- "Increased dashboard load speed by 60% (1.4s → 560ms)"

**Tier 2 (good):** Single concrete after-state metric.
- "Maintained 99.8% uptime across 5 Tier-1 services"
- "Saved 200+ engineering hours per month"

**Tier 3 (acceptable if Tier 1/2 unknown):** Scope or scale as proxy.
- "Served 50K daily users", "Processed $10B+ in transactions"
- "Across 30+ teams", "Indexed 50K documents"
- These say nothing about quality of YOUR work, but they say the system you
  touched mattered. Use when no improvement metric is available.

**Tier 4 (red flag — avoid):** Vague qualifier with no number.
- "Significantly improved performance" — what metric?
- "Optimized X" — by how much?
- "Reduced cost" — to what level?

## Honest Estimation

If you remember a metric was "around 40% faster" but don't have the exact
figure, write **"~40% reduction"** or **"approximately 40% faster"**. This is
honest; it signals the writer remembers the magnitude but not the digit.

Inventing precise-looking digits (e.g., writing "37.4% reduction" when you
only know it was "a lot faster") is a lie. Avoid it.

## When to Drop a Bullet Instead

If the work happened but no truthful metric is available **and** the scope is
unimpressive, drop the bullet entirely. A short, metric-rich bullet section
beats a long, vague one every time. Recruiters scan; they don't grade on
volume.

## Examples From This Master Resume

- **AutoFlow**: "cut automation setup time 95% across 20 engineering teams" —
  Tier 1.
- **Splunk dashboards**: "monitoring 200+ microservices" — Tier 3 (scope).
- **UBS incident response**: "99.8% uptime through root-cause analysis" —
  Tier 2.

All three say something. None inflate.
