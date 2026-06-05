---
title: Cover Letter Hook — Specificity Beats Enthusiasm
tags: [cover-letter, hook, voice, opening, anti-template]
role_fit: [swe, ml, ai, data, sre, pm]
applies_when: every cover letter
---

## The First Sentence Is the Filter

Recruiters give cover letters ~10 seconds. The opening sentence decides
whether the rest gets read. If it sounds like a template, the reader skims.
If it sounds like a person who read the posting, the reader engages.

## Banned Openings (template detectors)

These get the letter classified as automated within 2 seconds:
- "I'm writing to express my interest in the [Role] position at [Company]."
- "I'm passionate about [domain] and would love to contribute to [Company]."
- "I read your job posting for [Role] and was excited to apply."
- "Allow me to introduce myself — I'm a recent graduate of..."
- "As a [pronoun] with [N] years of experience..."
- "I came across your opportunity on [board]..."

If your draft starts with any of these, rewrite. They're free signal that
the writer didn't engage with the specific role.

## The Three Hook Patterns That Work

### Pattern 1: Problem-First (when JD is specific)

State the problem the role exists to solve, then bridge to a moment you
hit the same problem yourself.

> "Cloudflare's intern role asks for someone who can deploy AI services on
> Kubernetes and build MLOps tooling that lets product teams ship without
> an ML Eng. At UBS, the absence of that exact tooling was the week-long
> bottleneck I ended up solving with AutoFlow."

### Pattern 2: Domain-First (when JD is sparse)

Infer the company's problem space from its name + role title. State the
problem honestly with hedging ("often", "typically"), then bridge.

> "Financial services engineering teams often have to ship AI tools
> under regulatory, cost, and latency constraints — the kind of constraints
> that make the LangGraph pipeline I built at UBS feel like the closest
> analogue I've shipped."

### Pattern 3: Specific-Detail (when something from the JD jumps out)

Pick one concrete phrase from the JD and react to it.

> "Your posting mentions 'normalizing problems before they grow' as part
> of the platform team's culture. The most useful work I did at UBS came
> from spotting one such normalized problem — engineers spending a week
> on automation runbooks they could have written in five minutes — and
> building AutoFlow to fix it."

## What "Specific" Actually Means

A specific hook references **at least one of**:
- A phrase from the JD (Pattern 3)
- The company's product or domain (Patterns 1, 2)
- A problem the role exists to solve (Patterns 1, 2)

A specific hook does NOT reference:
- Your own credentials in the first sentence
- Your enthusiasm or passion
- "Allow me to" / "I am writing to" / any 18th-century preamble
- The company's stock price, founding year, or mission statement verbatim
  (these read as scraped)

## Don't Fabricate Specifics

If the JD says nothing about culture or stack, do NOT make up details. A
fabricated specific is worse than a generic opening. Use Pattern 2 instead.

Avoid:
- "I admire [Company]'s commitment to X" (where X isn't in the JD)
- "I've followed [Company]'s work in Y" (where Y isn't in the JD)

## Transitions Between Hook and Story Paragraph

The hook should set up the story paragraph without explicitly handing off:

- ❌ "Let me tell you about a time when..." (transition-y, weak)
- ❌ "Here's an example of my experience:" (clichéd)
- ✅ "At UBS, that exact problem cost us a week of engineering time. I
  fixed it like this..."  (the hook's problem reappears as a beat)

## Banned Closing Lines

Just as banned as banned openings:
- "Let's talk."
- "Can we talk?"
- "I'd like to talk."
- "Let me know if you'd like to chat."

These are over-casual and read as automated. Use the vetted closer:
- "I'd welcome the chance to discuss [specific JD point]."

The `validate_cover_letter` sanitizer will replace banned closers
automatically; this guide is for the LLM to avoid them in the first place.
