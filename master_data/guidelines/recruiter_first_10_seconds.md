---
title: The Recruiter's First 10 Seconds — Optimize the Scan
tags: [recruiter, scan, summary, density, layout, first-impression]
role_fit: [swe, ml, ai, data, sre, pm]
applies_when: every resume
---

## What Recruiters Actually Do

A corporate recruiter spends **6–10 seconds** on the initial scan of a
resume. Eye-tracking studies (Ladders 2018, TopResume 2020) show the gaze
pattern is roughly:

1. **Name + contact line** (1 sec — confirm spelling, location)
2. **First section header** (1 sec — usually Education or Experience)
3. **Top of Experience: first role's title + company** (2 sec)
4. **First bullet of the most recent role** (2 sec)
5. **Skills section header + first row** (2 sec)
6. **Quick downward scan for keywords or red flags** (2 sec)

If a YES emerges in those 10 seconds, they read more. If not, the resume
is rejected.

## Optimize Each Scan Stop

### Stop 1: Name + Contact

Plain. Centered. No graphics. Email + phone + LinkedIn + GitHub + portfolio
in one row. Avoid icons. Avoid two-column layouts that confuse ATS parsers.

### Stop 2: First Section

**Education** if you're a student or new grad with a strong school + GPA.
Place UW first; the recruiter sees a credentialing signal in 1 sec.

**Experience** if you have ≥1 year of professional work. The recruiter
sees a working professional in 1 sec.

For a student with strong internships, either works. Default to Education
for student-facing roles, Experience for industry-facing roles.

### Stop 3: First Role's Title + Company

The most recent role's title + company is the biggest single signal. Make
it bold. If your most recent role title is generic ("Software Engineer"),
add disambiguation in parens or via the bullet.

### Stop 4: First Bullet of the Most Recent Role

This is the **single highest-leverage line on the page**. It must:
- Lead with a strong action verb (Engineered, Architected, Shipped)
- Include the flagship metric (the 95% number, the $10B scope)
- Mention 1–2 technologies the JD asks for
- Fit on ONE printed line (90–105 chars) so the recruiter doesn't need
  to wrap their eye

If your first bullet doesn't pass these tests, move bullets around.

### Stop 5: Skills Section Header + First Row

The Skills section should be **near the top half of the page**, not buried
at the bottom. The first skill group should match the JD's primary
technology (Languages or AI/ML for a tech role; Cloud & DevOps for SRE).

Avoid "Soft skills: Communication, Leadership, Team Player." This is a
red flag — recruiters know strong candidates don't waste real estate on it.

### Stop 6: Downward Scan

This is where keyword density matters. Sprinkle JD-mirrored hard skills
into bullets organically. Don't keyword-stuff (e.g., "Used Python and
Java and Go and Rust") — recruiters and ATS systems both detect this.

## Summary Identity — Lead With "What You Are"

The summary's first 4 words are read in the first 2 seconds. They should
state **what role-type you are**, NOT a verb-led generic claim.

- ✅ "ML / AI engineer with 4+ years..."
- ✅ "Software engineer specializing in..."
- ✅ "Site reliability engineer who..."
- ❌ "Highly motivated computer science student..."
- ❌ "Detail-oriented self-starter with..."
- ❌ "Passionate technologist focused on..."

The role-type label primes the recruiter to match your profile to the JD.
The "highly motivated" opener primes them to dismiss.

## Density Rules That Affect the Scan

A page with too much whitespace = the recruiter wonders why. A page that
overflows = the recruiter doesn't see the bottom-half content.

- Target **59–62 body-line equivalents** on one page (out of ~62 budget).
- No half-empty bullet wraps (the `line_fitter` enforces this).
- Skills section: 4–8 items per group, 5–7 groups total.
- Bullets per role: 4–5 (UBS gets 5; older roles trim to 4).

## What Recruiters Will Reject Outright

- Photos / headshots (illegal to consider in US, but adds visual noise)
- Tables / columns / graphics that break ATS parsing
- Fonts other than TNR / Calibri / Arial / Garamond
- Margins under 0.2" (looks cramped) or over 0.75" (looks empty)
- Multi-color highlights (use grayscale or one accent color max)
- Page 2 unless your career is 10+ years deep

The bot already enforces most of these via the renderer. This guideline
exists so the LLM doesn't fight the renderer with rich-text suggestions.
