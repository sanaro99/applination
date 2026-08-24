# Onboarding as a journey — design

**Date:** 2026-08-24
**Status:** proposed
**Replaces:** the 7-step wizard in `web/app/onboarding/page.tsx`

## Why

The current onboarding is a correct, unremarkable form wizard: Welcome →
AI provider → Your details → Resume → Voice & stories → Search → Finish. It
front-loads every cost (an API key from a stranger, a resume, contact fields)
and defers every reward. Its most valuable step — stories, the thing that
actually differentiates the product — is labelled "optional" and buried at
position five.

The redesign turns setup into a conversation that produces a profile, and makes
the profile a permanent, visible asset rather than a wizard's exhaust.

This document assumes the product ethos: never invent a person; the corpus is
the product; your data is verifiably yours; talk to a friend, not a form;
invitation not gate; the assistant infers and the user corrects; earn belief
before asking for commitment; no dark patterns.

## Settled constraints

These were decided during brainstorming and are inputs, not open questions.

1. **No microphone code.** Voice happens through the user's own dictation tool
   (Wispr Flow, phone keyboard mic, OS dictation) writing into a normal text
   input. This keeps every browser working, keeps audio off third-party servers,
   and makes "your data stays yours" literally true. Pause-detection is a
   debounce on `input`, which behaves identically for typists and dictators.
2. **The API key is deferred to the end.** Nothing before the final chapter may
   require an LLM call.
3. **The fingerprint is a permanent profile-strength object**, not a wizard
   progress bar.
4. **Everything is optional**, including contact details, including the resume,
   including the whole journey.

### Consequence: capture and enrichment are separate passes

Because no LLM is available during the journey, the journey may only *capture
raw human material*. Every AI transformation — resume text into `resume.yaml`,
a spoken ramble into a tagged story, freeform notes into `bio.md` — moves into a
separate **enrichment pass** that replays once a provider key exists.

This is a better architecture than the current inline-extract-on-upload flow
regardless of the key question: capture never fails because a model was down, a
key was wrong, or a quota was hit, and enrichment is independently retryable.

## The journey

Six chapters, one question each, full-bleed, then the dashboard. Not a chat thread — it never
claims to be an AI talking, so scripted warmth reads as considered copy rather
than a model failing to be a model. Warmth comes from reflecting captured data
back specifically ("Three roles, most recent at Stripe through March"), not from
emoting.

Every chapter carries: a **Skip** affordance, a **Use a sample** affordance, and
autosave.

### 1 · The frame

States what the product is, what it will do, and what it will never do:

> Nothing in your documents will ever say something you didn't say first.

Names where the files live (`data/users/<id>/`), links to the public repository,
and says plainly that none of this is required and all of it is editable
forever. Offers "just take me in" as a visible link, not a hidden escape.

The fingerprint appears here — faint, mostly unformed.

Rationale: this frame is what makes someone willing to talk in chapter 2. It
also converts two differentiators (anti-fabrication, verifiable data ownership)
into something the user actually sees, rather than README claims.

### 2 · Just talk

One question, one large forgiving input:

> So — what have you been working on lately?

No fields, no validation, no length requirement. Beneath it, offered rather than
demanded:

> Or drop your resume and I'll read it instead of making you type.

The resume is a shortcut *inside* the conversation. If given, its text is
extracted (`server/onboarding._extract_text`, already exists, no LLM) and
**parked** — not parsed into YAML, which needs a model.

### 3 · Follow the thread

From whatever chapter 2 produced — a paragraph, a resume, or both — we surface
the concrete things the user mentioned as selectable chips:

> `Stripe` · `the payments migration` · `that side project` · `something else`
>
> Which of these do you want to tell me about?

They pick one; we ask about *that*, in a friend's register:

> What were you actually doing there?
> How did it go?
> What was the annoying part?

Explicitly **not** interview questions. "Tell me about something you're proud
of" returns the rehearsed LinkedIn version — abstract, polished, useless as raw
material for a cover letter. "What was the annoying part" returns specifics,
constraints and judgement, which is exactly what makes generated prose stop
sounding generated.

Each telling is saved verbatim as a **draft story**. One ridge each. "That's
enough for now" stays on screen throughout; the loop is user-terminated, never
gated on a count.

Letting the user pick the thread also removes the need for a model: with no key
we cannot generate an intelligent follow-up, but we do not have to — their own
words are the menu, and being asked about the specific thing you just mentioned
reads as listening, not as guessing.

### 4 · "Here's what I think you're for"

Editable chips derived from the user's own words:

> `Backend Engineer` `Python` `distributed systems` `remote, or Bangalore`
>
> This is what I'd go looking for. Change anything that's wrong.

The assistant proposes; the user corrects. This is the inversion that matters:
the user never fills in a job-search form. First pass is deterministic
extraction (below). Once a key exists, enrichment re-reads the full corpus and
sharpens these.

Settling this chapter fires `fetch_all()` in the background.

### 5 · The payoff

> 1,247 live roles right now, across nine boards. 88 look like you.

Real postings, real companies, scrollable. Costs zero tokens, because
`src/main.py:121 fetch_all()` is pure HTTP.

This is the moment a first-time user believes the product exists. Most adjacent
tools cannot show this screen at all — they are a wrapper around a rewrite
prompt and have no inventory to show.

### 6 · Ignition

Contact details and the provider key together, because they share one
justification:

> To put your name on a document I need your details. To actually write it, I
> need a provider.

Contact fields pre-fill from the parked resume text where possible.

#### Provider choice

The user picks a provider before being asked for a key. **Gemini is the
recommended default** — it has a genuine free tier with no card required, and
most people already have a Google account and no reason to distrust it. This is
already the shipped default (`config.example.yaml:90`, and the wizard's picker
initialises to `gemini`); the journey keeps it and makes the reasoning visible
rather than implicit.

DeepSeek stays available but is **not** offered first. It is the cheapest paid
path and a fine choice for someone who has decided to pay, but presenting it as
the default to a stranger asks them to hand card details and prompts to a
provider many will not recognise, at the exact moment they have least reason to
trust us. Cheapness is not the right default when the user has no trust yet.

Note: `CLAUDE.md` still describes DeepSeek as "the default provider," which
contradicts `config.example.yaml`. That doc line should be corrected.

#### Setup instructions, and keeping them fresh

Each provider gets real setup instructions, not a bare hostname hint (today's
`PROVIDERS` array carries one-liners like `"platform.deepseek.com"`). Provider
metadata moves out of the frontend array into `server/provider_setup.py`, served
by `GET /api/providers/setup`, so the CLI, the Config page and the journey all
read one source:

```
id, label, recommended, why, model,
console_url      deep link straight to the key-creation page
steps            at most three lines describing what they will see
key_shape        prefix + length, for a client-side sanity check before we
                 spend a real call on an obviously malformed key
cost_note        qualitative only
verified_on      ISO date
```

Staleness is the stated risk, so it is designed against directly:

1. **Deep link over transcription.** The primary control is a button to
   `console_url`, not a click path. Steps stay at three shallow lines describing
   what the user will *see*; shallow instructions survive a vendor redesign,
   nine-step click paths do not.
2. **Never quote numeric limits or prices.** "Has a free tier, no card needed"
   is durable; "1,500 requests/day" is wrong within a quarter — Gemini's free
   tier has already narrowed to Flash-only while this design was being written.
   Numbers belong on the vendor's page, which is one click away.
3. **`verified_on` is shown in the UI** ("Checked 24 Aug 2026"). Past ~90 days
   the card softens its own wording to note the steps may have moved and the
   link is authoritative. The UI degrades honestly instead of lying confidently.
4. **`scripts/check_provider_links.py`** asserts each `console_url` still
   resolves and has not been redirected to a marketing homepage or a 404. Run
   manually or on a schedule and **not** as a unit test — network flake must
   never break the build. A green run is what licenses bumping `verified_on`.
5. **Failure feeds back.** When the live connection test returns an auth error,
   the message links back to that provider's setup card. A spike of failures on
   one provider is the signal that its instructions have rotted.

The live connection test stays, and runs before the cascade.

On success, the **enrichment cascade** runs, client-driven and step-by-step so
that each completed step visibly fills its ridge: parked resume text becomes
`resume.yaml`; each draft story becomes a tagged story; freeform notes become
`bio.md`; search chips sharpen. This cascade *is* the celebration — the
fingerprint completing itself — and it is the reward for having deferred the
key rather than an apology for it.

If the user skips the key, they land on the dashboard with drafts intact and a
single clear call to action. Nothing is lost.

### 7 · Dashboard

The fingerprint moves to a permanent card. See below.

## The fingerprint

### Two phases, both honest

An earlier sketch had the fingerprint "never full." That is a dark pattern and
contradicts the ethos, so it is not the design. Instead:

**Phase 1 — Formation.** A finite set of setup ridges that genuinely completes
at 100%. Reaching it is a real milestone and is celebrated.

| ridge | filled when |
|---|---|
| `contact` | `user.full_name` and `user.email` are real (not placeholders) |
| `material` | parked resume text **or** ≥1 draft/real story exists |
| `resume` | `master_data/resume.yaml` exists |
| `story_1..3` | 1st, 2nd, 3rd story exists (draft counts as half-filled) |
| `voice` | `master_data/bio.md` exists |
| `search` | `search.keywords` is non-empty |
| `provider` | a usable provider key is stored |

Draft-vs-real is what makes the cascade in chapter 6 visible: drafts render as
half-filled ridges that complete during enrichment.

**Phase 2 — Depth.** After formation, the card stops showing a percentage and
starts showing **story coverage against the committed tag taxonomy** in
`master_data/stories/_INDEX.md`:

> Your stories cover `backend`, `platform`, `python`. Nothing yet for
> `leadership` or `ml` — roles tagged that way will get a weaker letter.

This is not gamification theatre. `reference_loader.match_stories()` scores by
tag overlap, so a coverage gap is a *measurable, real* weakness in the output the
user is about to receive. The nudge is true, which is the only kind worth
shipping.

### Component notes

- SVG, ridges as `path` elements keyed by ridge id, filled via
  `stroke-dashoffset` with `motion` (already a dependency).
- The fingerprint is never the only progress signal: a text counter over the
  nine formation ridges ("4 of 9 filled") and an `aria-live` region carry the
  same information for anyone the metaphor fails.
- `prefers-reduced-motion` disables the fill animation; state still updates.

## Deterministic extraction

New module `src/intake_extract.py` — pure functions, no LLM, no I/O, unit
testable in isolation.

```
extract_threads(text: str, resume_text: str = "") -> list[Thread]
extract_search_terms(text: str, resume_text: str = "") -> SearchTerms
```

Sources, in confidence order:

1. **Company names** matched against the existing
   `src/scrapers/greenhouse_companies.py` list.
2. **Vocabulary terms** matched against the tag taxonomy already committed in
   `master_data/stories/_INDEX.md` (technical areas, specific tech, role types).
   Parsing that file gives us a curated vocabulary for free and keeps extraction
   and matching using the same words.
3. **Verb-anchored noun phrases** — text following "worked on", "built", "led",
   "shipped", "migrated".
4. **Resume structure** — job titles and employers, when resume text was parked.

Guards: a stoplist for corporate noise (`Inc`, `Ltd`, `LLC`, `Technologies`),
a cap of 8 chips, minimum length 3, and "something else" always present. Bad
chips are the main embarrassment risk here, so the bias is strongly toward
precision over recall — showing four good chips beats showing eight with two
absurd ones.

`extract_search_terms` degrades to a small default set with explicitly hedged
copy ("I'm guessing here — fix this") rather than pretending to confidence.

## Storage

New per-user intake area, owned by `server/user_paths.py` (never joined by
hand — `resolve_within` remains the single door):

```
data/users/<id>/master_data/_intake/
    resume_raw.txt          parked resume text
    notes.md                the chapter-2 freeform answer
    stories/<slug>.md       draft stories, frontmatter draft: true, captured_at
    consumed/               drafts moved here after enrichment, never deleted
```

`_intake/` is underscore-prefixed, consistent with the existing `_INDEX.md`
convention, and sits outside `stories/` so `reference_loader` and
`onboarding._count_stories` do not pick drafts up as real stories. Drafts are
moved to `consumed/` rather than deleted so a failed or unsatisfying enrichment
never destroys the user's own words.

`UserPaths` gains `intake_dir`, `intake_stories_dir`, `intake_resume_path`,
`intake_notes_path`, and `ensure()` creates them.

## Backend changes

All new routes live under the existing authenticated `/api/onboarding` router
(`server/onboarding.py`), which already carries `Depends(require_user)`. Every
new DB query goes through `server/scoping.py` or carries an explicit
`# noscope:` — `tests/test_scope_lint.py` enforces this.

### New endpoints

| method | path | purpose |
|---|---|---|
| `POST` | `/api/onboarding/intake/notes` | save chapter-2 freeform text |
| `POST` | `/api/onboarding/intake/resume` | multipart upload → extract text → park it (**no LLM**) |
| `GET` | `/api/onboarding/intake/threads` | deterministic chips for chapter 3 |
| `POST` | `/api/onboarding/intake/story` | save one draft story verbatim |
| `GET` | `/api/onboarding/intake/search-terms` | deterministic chips for chapter 4 |
| `POST` | `/api/onboarding/preview-jobs` | run `fetch_all()` for chapter 5, cached |
| `GET` | `/api/onboarding/enrich/plan` | ordered list of pending enrichment steps |
| `POST` | `/api/onboarding/enrich/step` | run one step by id; idempotent |
| `GET` | `/api/profile/strength` | ridges + phase + coverage (new `server/profile_strength.py`) |
| `GET` | `/api/providers/setup` | provider metadata + setup steps (new `server/provider_setup.py`) |

### Changed

- `POST /api/onboarding/resume-import` keeps working unchanged for users who
  already have a key — the journey simply does not call it.
- `GET /api/onboarding/status` gains an `intake` block so the gate can tell
  "never started" from "started, drafts parked, no key".

### Enrichment steps

The client drives the cascade one step at a time so that ridge animation
reflects real progress rather than a timed fake, and so any single failure is
retryable in place without restarting.

| step | input | output | provider task |
|---|---|---|---|
| `resume` | `_intake/resume_raw.txt` | `master_data/resume.yaml` | `content_studio` |
| `story:<slug>` | one draft | `master_data/stories/<slug>.md` | `content_studio` |
| `bio` | `_intake/notes.md` | `master_data/bio.md` | `content_studio` |
| `search` | full corpus | proposed keywords (**not** auto-written) | `content_studio` |

`search` proposes and returns; it never silently rewrites the user's chips.
Every step is idempotent: skipped if its output already exists, unless
`force=true`.

### Job preview caching

`fetch_all()` hits nine external services and is slow. `POST /preview-jobs`
returns immediately with a job id; the client polls for completion while the
user is still in chapter 4. Results cache per user for 30 minutes. **Chapter 5 must degrade gracefully**: on timeout or partial
source failure it shows what it has ("across 6 of 9 boards") and never blocks
progression to chapter 6.

Note: `src/scrapers/simplify_github.py:248` still writes its JD cache to a
repo-root `output/.jd_cache`, a pre-multi-user path. Out of scope here, but it
will be exercised by this feature and should be filed separately.

## Frontend changes

`web/app/onboarding/page.tsx` is 795 lines holding seven step components. It is
decomposed as part of this work — not gratuitous refactoring, but because every
chapter changes and the file is already past the size where edits are reliable.

```
web/components/onboarding/
    journey-shell.tsx        full-bleed chapter frame, skip + sample affordances
    fingerprint.tsx          SVG ridges, motion fill, aria-live counter
    dictation-box.tsx        large autosaving input, debounced pause reflection
    sample-fill.tsx          "use a sample" control
    chapters/01-frame.tsx … 07-done.tsx
    use-journey-store.ts     zustand + localStorage persistence
```

`web/app/onboarding/page.tsx` becomes a thin router over chapters.

**Draft durability matters more than it looks.** A user who dictates for ninety
seconds and loses it to a reload will not do it twice. State persists to
`localStorage` on every change *and* autosaves to the server per chapter.

`web/components/onboarding-gate.tsx` is unchanged in shape; it reads the
extended status.

## Sample data

Every chapter offers **"use a sample"**, sourced from the committed `demo_data/`
John Doe fixture — already fictional and public-repo-safe, so it costs nothing
to reuse.

Two non-negotiable conditions:

1. Sample-filled values are **visibly marked** as sample — a tint in the
   journey, and a persistent banner on the dashboard while any sample value
   remains in the user's config or master data.
2. **One-click wipe**, offered in that banner.

Sample data silently becoming someone's real cover letter is the single most
likely way this feature turns into a bug report, so the marking is part of the
feature, not polish on it.

## Risks

| risk | mitigation |
|---|---|
| Everything optional → user skips all → empty dashboard | Make chapter 2 easier to answer than to skip: one question, one box, no commitment. The fingerprint carries the rest afterwards. Accepted rather than gated. |
| Extraction produces embarrassing chips | Precision-biased vocabulary matching, stoplist, low cap, "something else" always available. |
| A long dictated answer lost on reload | localStorage on change + server autosave per chapter. |
| `fetch_all` slow or partially failing in chapter 5 | Degrade to partial counts, never block. |
| Sample data leaking into real documents | Visible marking, persistent banner, one-click wipe. |
| Enrichment fails mid-cascade | Per-step, idempotent, retryable; drafts preserved in `consumed/`. |
| Provider setup instructions rot | Deep links over click paths, no numeric limits, visible `verified_on` that degrades its own wording, link checker, auth-failure feedback loop. |

## Testing

- **`src/intake_extract.py`** — unit tests, the bulk of the value. Pure
  functions: fixture texts in, expected chips out, including the stoplist and
  precision guards.
- **Enrichment idempotency** — running each step twice produces one output and
  no duplicate stories.
- **Intake path containment** — draft slugs are user-influenced; assert
  `resolve_within` rejects traversal.
- **Scope lint** — `tests/test_scope_lint.py` must stay green.
- **Status transitions** — `/status` reports "started, no key" correctly.
- **Frontend** — `npm run build` and `npm run lint` only; visual verification is
  the user's.

## Out of scope

- Microphone capture or server-side transcription.
- Any LLM call before chapter 6.
- The `simplify_github` global cache path bug.
- Reworking `/master-data`, `/config`, or the coach surfaces, beyond the
  fingerprint card appearing on the dashboard.
