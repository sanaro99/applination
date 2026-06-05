# Cover Letters Library

Two things live here:

## `examples/` — past cover letters as style references

Drop your previously-written cover letters here (as `.md` or `.txt`) with
frontmatter, and the builder will include the most-relevant one as a *style
example* in the prompt when writing new letters. This way, the AI learns
your actual voice over time instead of the generic "helpful assistant" voice.

Template:

```markdown
---
title: "UBS Zurich Software Engineer Intern"
tags: [finance, ubs, return-to-company, swe]
role_fit: [swe]
company_fit: [finance, enterprise]
company: "UBS"
role: "Software Engineering Intern"
date: "2026-04-01"
---

[paste the actual letter you sent, minus the contact header/date]
```

The more examples you add, the more your voice becomes the baseline. One or
two per category is enough.

## How matching works

When writing a new cover letter, the builder:
1. Extracts keywords from the JD (company, role, required skills)
2. Scores each file in `examples/` by tag overlap with those keywords
3. Passes the top-scored example into the prompt as a "write in this style" anchor
4. Also picks 1–2 stories from `../stories/` by the same process
5. Writes the new letter in email-style (no rigid 3-paragraph structure)

If no example matches (e.g., a totally new category of company), the builder
falls back to the voice guidelines in `../bio.md`.

## Recommended categories to have examples for

You'll want at least one example letter for each combination you apply to
regularly. Suggested starting set:

- `tags: [finance, swe]` — for banks, trading, fintech
- `tags: [bigtech, swe]` — for FAANG-ish
- `tags: [startup, swe]` — for early-stage
- `tags: [ai-first, ml]` — for AI companies (Anthropic, OpenAI, etc.)
- `tags: [platform, devtools]` — for dev infrastructure companies
- `tags: [mission-driven]` — for impact-focused companies

You don't need all of these to start. Add examples as you write good
letters you'd want the AI to imitate.
