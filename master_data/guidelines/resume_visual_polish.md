---
title: Resume Visual Polish — Density, Spacing, One-Page Balance
tags: [visual, spacing, density, line_fill, whitespace, one_page, formatting, balance]
role_fit: [swe, ml, data, sre, pm, ai]
applies_when: all resume rendering — visual completeness check before submitting
---

## The One-Page Contract

A one-page resume should look like a full page — not a half-page with whitespace below, not an overflow onto a second page. Both extremes signal a candidate who didn't control their output.

**Target visual density:** 90–100% of the printable area should contain content. The bottom margin should be visually close to the top margin. Empty bottom half = underprepared.

## Section Order for Visual Weight

Place heaviest content sections first so the page fills from the top down:

1. Contact / Header (fixed, compact)
2. Summary (2–3 lines — identity statement, not padding)
3. Experience (heaviest section — 2 entries × 4 bullets each)
4. Projects (3 entries × 2 bullets each)
5. Skills (5–6 groups, 4–8 items per group)
6. Education (2 entries, compact)
7. Certifications / Awards (1 line each, compact)

If the page has visible empty space below Education, the problem is either: too-short bullets, too-sparse skills, or a missing project entry.

## Line-Fill Rule (applies to every bullet)

Bullets that end at 40–70% of line width leave a visual half-line blank. This is the most common source of "empty looking" resumes.

**Target per bullet** (10pt TNR, ~132 chars/printed line; authoritative bands in
`src/line_fitter.py::configure_for_font`):
- **One-liner:** 116–125 characters — packs the line nearly edge-to-edge (≥~88% full)
- **Two-liner:** 205–258 characters — fills two lines; line 2 at least ~55% width
- **Never:** the 126–204 forbidden zone (orphan wrap), or under ~116 (an under-filled single line). Expand with the missing PAR component / scope / metric.

This applies to experience bullets AND project bullets. Project bullets are often written shorter — they shouldn't be.

## Skills Section Visual Density

Each skill group renders as one line: `GroupName: item1, item2, item3, ...`

A group with 1–2 items renders as a half-empty line. A group with 6–8 items fills the line.

**Target per group:** 4–8 items minimum. Six groups × 5 items = 30 total, which fills approximately 6 lines of the skills section — about right for density.

**Never:** Groups with 1–2 items only. Merge them into adjacent groups or fill from the master skill pool.

## Summary Section

Should fill 2–3 lines at standard font size. A one-line summary looks like a placeholder. A 5-line summary wastes valuable experience space.

**Optimal:** 200–280 characters (roughly 2 lines at 10.5pt Times New Roman).

The summary should not repeat information that's already obvious from the experience section — it should add the identity framing (what type of engineer you are) and a flagship metric.

## Certifications and Awards Section

These are compact sections — one line each is correct. Use a `•` separator between items on the same line, not a `|` bar (which reads as a table separator, not a list).

**Good:** `AWS Solutions Architect (2024)  •  Google Cloud Professional  •  Azure AZ-900`
**Bad:** `AWS Solutions Architect (2024) | Google Cloud Professional | Azure AZ-900`

If there's only one certification or one award, that's fine — it still gets its own section if it's notable.

## Education Section

Each education entry takes 2–3 lines:
- Line 1: School + location (bold) + dates (right-aligned or trailing)
- Line 2: Degree + GPA (if notable, i.e., ≥ 3.5)
- Line 3 (optional): Coursework: X, Y, Z — only if relevant to the JD

Never add coursework that isn't relevant. 4–6 courses maximum, comma-separated, no "and."

## Contact Header

One line of contact info with separators. Email, phone, LinkedIn, GitHub, location — in that order. Use `|` between contact items (this is the one place `|` is correct on a resume). Keep it compact — no more than one line.

## Visual Balance Checklist (pre-submit)

Before generating the final PDF, confirm:
- [ ] No section is blank or has only 1 item when 3–4 would fit
- [ ] No bullet ends at less than 80% of line width
- [ ] Skills section has ≥ 25 items across ≥ 5 groups
- [ ] Bottom of page is within 2–3 lines of the bottom margin
- [ ] Summary is 2–3 lines, not 1, not 5
- [ ] No `|` separator in certifications or awards (use `•`)
- [ ] Education coursework is ≤ 6 items, JD-relevant only
