---
title: Resume Density — Why 116-125 OR 205-258 Chars, Nothing In Between
tags: [density, rendering, line-fill, one-page, layout]
role_fit: [swe, ml, ai, data, sre, pm]
applies_when: all experience and project bullets
---

## The Physics of the Page

The resume is rendered in **Times New Roman 10pt** at **0.25" L/R margins**.
This yields roughly **132 characters per printed line** of body text. (The
authoritative, font-aware bands live in `src/line_fitter.py::configure_for_font`;
the numbers here are the 10pt values and change if the body font changes.)

A bullet's character count determines how it wraps:
- **~79–125 chars:** fits on one printed line.
- **126–258 chars:** wraps to two printed lines.
- **259+ chars:** risks wrapping to a third printed line.

A single-line bullet of only ~95 chars renders as:
```
• ipsum lorem dolor sit amet consectetur adipiscing elit sed do eiusmod
```
The right ~third of the line is empty whitespace — the bullet under-fills its
line. Pack it to ~116–125 chars so the line runs nearly edge-to-edge.

## The Two Allowed Bands

**Single-line: 116–125 chars.** The first line packs nearly to the edge
(≥~88% full); nothing wraps. Best for crisp, metric-led bullets where one PAR
ladder is enough. Do not stop short around 90–110 — that under-fills the line.

**Double-line: 205–258 chars.** Both lines pack with line 2 at least ~55%
full. Used when a bullet has rich context, multiple metrics, or technical
specifics that deserve two lines.

## The Forbidden Zone: 126–204 Chars

Any bullet whose length is 126–204 chars will wrap to a second line, but
that second line will be mostly empty. Visible whitespace eats vertical
real estate the resume could have packed with another bullet.

If a draft bullet falls into this range, the system will:
1. Try to swap it for a longer master variant (`bullets_all` entries in the
   205–258 band) whose first 6 words overlap with the current bullet — so
   the topic stays the same but the result component is richer.
2. If no master match is found, the bullet is **kept intact**. Never
   truncated. A complete bullet with PAR Result beats a half-bullet with
   no metric.
3. Only in extreme cases (deep forbidden zone, no master match, safe trim
   couldn't help) does the bullet escalate to an LLM rewrite pass.

## Why We Don't Truncate to Fit

Earlier versions of the line_fitter tried to drop trailing clauses ("...; reduced
MTTD 60%" → "...") to bring bullets under the single-line max. This produced
bullets ending mid-sentence or missing their PAR Result entirely. **Truncation
is worse than wrap-waste.** A 150-char bullet wrapping with a half-empty line 2
is still readable; a 75-char bullet ending in "...team emails" with no
outcome is just incomplete.

## Page-Budget Implications

At 10pt TNR with the standard layout, **about 60 body-line equivalents fit
on one page** (headings count as ~1.6 body lines each). The target is
**~54–60 lines** for a packed page that doesn't overflow.

If experience bullets are all single-line, allow more skill-group rows or
add a third project. If experience bullets are all double-line, drop
coursework or the third project to compensate.

## Why "Just Use Double-Line Everywhere" Doesn't Work

Double-line bullets are denser, so it's tempting. But:
- They demand more content. If you only have one metric, padding to 200
  chars produces visibly weak prose.
- Recruiters scan five bullets per role; if all five are 200 chars, scan
  fatigue sets in. Mixing single and double signals **range**: some thoughts
  are quick wins, some are deeper.

A balanced experience entry has **2 single-line + 2 double-line** bullets.
The renderer expects 4–5 bullets per role.

## What This Document Constrains

- The `_run_tailor` and `_run_revise` prompts reference the single (116-125) /
  double (205-258) rule explicitly, interpolated live from `line_fitter`.
- The `line_fitter` post-process classifies bullets into bands and only
  substitutes from master where safe.
- The `_run_critique` step lists "forbidden zone bullets" as a flagged issue.

Truthful, concrete, complete — in that order. In-band is a bonus, never at
the cost of completeness.
