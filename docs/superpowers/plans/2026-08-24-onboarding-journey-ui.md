# Onboarding Journey UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the seven-step form wizard with the six-chapter journey: a conversation that produces a profile, with the fingerprint as its permanent visible artifact.

**Architecture:** `web/app/onboarding/page.tsx` becomes a thin router over chapter components in `web/components/onboarding/`. A zustand store holds in-flight answers and persists to `localStorage` so a reload never costs the user a ninety-second dictated answer. The fingerprint is an SVG whose ridges map 1:1 to the ridge ids from `GET /api/profile/strength`.

**Tech Stack:** Next.js 16 (App Router, Turbopack), React 19, Tailwind v4, shadcn/ui + MagicUI, TanStack Query, zustand, `motion`.

**Spec:** `docs/superpowers/specs/2026-08-24-onboarding-journey-design.md`

**Predecessors:** plan 1 (complete) and plan 2 (`/api/profile/strength`, `/api/providers/setup`, `/api/onboarding/preview-jobs`, `/api/onboarding/enrich/*`). **Do not start this plan until plan 2 is merged** — every chapter calls one of its endpoints.

## Verification note — read this first

Per the project's standing preference, **frontend work is verified with `npm run build` and `npm run lint` only**; visual checking is the user's. That is weaker verification than plans 1 and 2 had, and it is deliberate. The consequence: this plan puts as much logic as possible into pure, testable helpers (`ridge-geometry.ts`, `sample-data.ts`) that *do* get unit tests, leaving components as thin rendering shells.

## Global Constraints

- **Every chapter is skippable**, and says so. No chapter may gate progress.
- **No chapter before 6 may trigger an LLM call.** Chapters 1–5 use only plan-1 intake endpoints and the LLM-free job preview.
- **Never lose a dictated answer.** Persist to `localStorage` on change *and* autosave to the server per chapter.
- **Friend register, not interview register.** No chapter may ask "tell me about a challenge you overcame", "something you're proud of", "your greatest strength", or any variant. Ask what they were doing, how it went, what was annoying.
- **Sample data must stay visibly marked** and be wipeable in one click.
- **Respect `prefers-reduced-motion`** — the fingerprint updates state without animating.
- The fingerprint is never the only progress signal: a text counter and an `aria-live` region carry the same information.
- Run `npm run build` and `npm run lint` from `web/` at the end of every task.

---

## File Structure

| File | Responsibility |
|---|---|
| `web/lib/api.ts` *(modify)* | Types + methods for the plan-1 and plan-2 endpoints. |
| `web/lib/ridge-geometry.ts` *(create)* | Pure: ridge id → SVG path + fill fraction. Unit tested. |
| `web/lib/sample-data.ts` *(create)* | Pure: the John Doe sample answers, per chapter. Unit tested. |
| `web/components/onboarding/fingerprint.tsx` *(create)* | The SVG, animation, a11y counter. |
| `web/components/onboarding/journey-shell.tsx` *(create)* | Chapter frame: heading, body, skip, sample, back/next. |
| `web/components/onboarding/dictation-box.tsx` *(create)* | Large autosaving textarea with debounced pause reflection. |
| `web/components/onboarding/use-journey-store.ts` *(create)* | zustand + localStorage. |
| `web/components/onboarding/chapters/*.tsx` *(create)* | Six chapters. |
| `web/app/onboarding/page.tsx` *(rewrite)* | Thin router. |
| `web/components/profile-strength-card.tsx` *(create)* | The dashboard's permanent fingerprint. |
| `web/components/sample-data-banner.tsx` *(create)* | Persistent marker + one-click wipe. |
| `server/onboarding.py` *(modify, Task 6)* | Two small routes backing the sample marker. |

---

### Task 1: API client surface

**Files:**
- Modify: `web/lib/api.ts`
- Test: `web/lib/__tests__/` is not established in this repo — verification is `npm run build`.

**Interfaces produced** (add to the `api` object and export the types):

```ts
export type Ridge = {
  id: string; label: string; hint: string;
  state: "empty" | "partial" | "filled";
};
export type ProfileStrength = {
  phase: "formation" | "depth";
  filled: number; partial: number; total: number; score: number;
  ridges: Ridge[];
  next: { id: string; label: string; hint: string } | null;
  coverage: { covered: string[]; gaps: string[] };
};
export type ProviderSetup = {
  id: string; label: string; recommended: boolean; why: string; model: string;
  console_url: string; steps: string[];
  key_shape: { prefix: string; min_len: number };
  cost_note: string; needs_key: boolean; verified_on: string; stale: boolean;
};
export type IntakeThread = { label: string; kind: "company" | "topic" | "phrase" };
export type JobPreview = {
  state: "idle" | "running" | "ready" | "error";
  total: number; matched: number;
  sources_ok: number; sources_total: number;
  sample: { title: string; company: string; location: string; url: string }[];
  error: string | null;
};
export type EnrichStep = { id: string; label: string; ridge: string };
```

- [ ] **Step 1: Add the methods**

Append inside the `api` object in `web/lib/api.ts`, following the existing `http<T>(...)` style:

```ts
  profileStrength: () => http<ProfileStrength>("/api/profile/strength"),
  providerSetup: () =>
    http<{ providers: ProviderSetup[] }>("/api/providers/setup"),

  saveIntakeNotes: (text: string) =>
    http<{ ok: boolean }>("/api/onboarding/intake/notes", {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  parkIntakeResume: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return http<{ ok: boolean; chars: number }>(
      "/api/onboarding/intake/resume",
      { method: "POST", body: form },
    );
  },
  saveIntakeStory: (title: string, body: string) =>
    http<{ ok: boolean; slug: string }>("/api/onboarding/intake/story", {
      method: "POST",
      body: JSON.stringify({ title, body }),
    }),
  intakeThreads: () =>
    http<{ threads: IntakeThread[] }>("/api/onboarding/intake/threads"),
  intakeSearchTerms: () =>
    http<{ keywords: string[]; guessed: boolean }>(
      "/api/onboarding/intake/search-terms",
    ),

  startJobPreview: () =>
    http<{ state: string }>("/api/onboarding/preview-jobs", { method: "POST" }),
  jobPreview: () => http<JobPreview>("/api/onboarding/preview-jobs"),

  enrichPlan: () => http<{ steps: EnrichStep[] }>("/api/onboarding/enrich/plan"),
  enrichStep: (step_id: string, force = false) =>
    http<{
      id: string; done: boolean; skipped: boolean;
      ridge: string; result: unknown;
    }>("/api/onboarding/enrich/step", {
      method: "POST",
      body: JSON.stringify({ step_id, force }),
    }),
```

**Check `http`'s body handling before writing `parkIntakeResume`.** If it sets `Content-Type: application/json` unconditionally, the multipart upload will fail — the browser must set that header itself so the boundary is correct. Read `web/lib/api.ts:60-107`; if the header is hardcoded, make it conditional on the body not being a `FormData`.

- [ ] **Step 2: Verify**

```bash
cd web && npm run build && npm run lint
```
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add web/lib/api.ts
git commit -m "feat(web): api client for intake, strength, preview and enrichment"
```

---

### Task 2: The fingerprint

**Files:**
- Create: `web/lib/ridge-geometry.ts`
- Create: `web/components/onboarding/fingerprint.tsx`
- Test: `web/lib/ridge-geometry.test.ts` (if no test runner is configured, skip the test file and note it in the commit — do not fake a passing test)

**Interfaces produced:**
- `RIDGE_ORDER: readonly string[]` — the nine ids in render order.
- `ridgePath(index: number): string` — SVG path `d` for ridge `index` (0-based, inner to outer).
- `fillFraction(state: "empty" | "partial" | "filled"): number` — 0, 0.5, 1.

- [ ] **Step 1: Write the geometry**

Create `web/lib/ridge-geometry.ts`:

```ts
/**
 * Fingerprint ridge geometry.
 *
 * Pure and separate from the component so it can be reasoned about (and tested)
 * without a DOM. Ridges are concentric arcs, innermost first, matching the ridge
 * order the API returns — ridge N always means the same thing, so the shape a
 * user watches fill is stable across sessions.
 */
export const RIDGE_ORDER = [
  "contact", "material", "resume", "story_1", "story_2",
  "story_3", "voice", "search", "provider",
] as const;

const CENTER = 60;
const INNER_RADIUS = 8;
const RIDGE_GAP = 5.5;

/** An open arc, flattened slightly so it reads as a fingerprint, not a target. */
export function ridgePath(index: number): string {
  const r = INNER_RADIUS + index * RIDGE_GAP;
  const ry = r * 1.18;
  // Leave a gap at the bottom so the rings read as ridges rather than circles.
  const startAngle = 115;
  const endAngle = 425;
  const rad = (deg: number) => (deg * Math.PI) / 180;
  const x1 = CENTER + r * Math.cos(rad(startAngle));
  const y1 = CENTER + ry * Math.sin(rad(startAngle));
  const x2 = CENTER + r * Math.cos(rad(endAngle));
  const y2 = CENTER + ry * Math.sin(rad(endAngle));
  return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r.toFixed(2)} ${ry.toFixed(2)} 0 1 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
}

export function fillFraction(state: string): number {
  if (state === "filled") return 1;
  if (state === "partial") return 0.5;
  return 0;
}
```

- [ ] **Step 2: Write the component**

Create `web/components/onboarding/fingerprint.tsx`:

```tsx
"use client";

/**
 * The fingerprint: a profile that is unique, owned, and not transferable.
 *
 * Not a progress bar in costume — the ridges map 1:1 to real profile state from
 * GET /api/profile/strength, and the thing genuinely completes. A draft story
 * shows as a half-filled ridge and finishes during the enrichment cascade,
 * which is what makes that moment read as a reward rather than a wait.
 */
import { motion, useReducedMotion } from "motion/react";

import { RIDGE_ORDER, fillFraction, ridgePath } from "@/lib/ridge-geometry";
import type { Ridge } from "@/lib/api";
import { cn } from "@/lib/utils";

export function Fingerprint({
  ridges,
  filled,
  total,
  className,
  size = 120,
}: {
  ridges: Ridge[];
  filled: number;
  total: number;
  className?: string;
  size?: number;
}) {
  const reduced = useReducedMotion();
  const byId = new Map(ridges.map((r) => [r.id, r]));

  return (
    <div className={cn("flex flex-col items-center gap-2", className)}>
      <svg
        width={size}
        height={size}
        viewBox="0 0 120 120"
        role="img"
        aria-label={`Profile fingerprint, ${filled} of ${total} parts complete`}
      >
        {RIDGE_ORDER.map((id, i) => {
          const state = byId.get(id)?.state ?? "empty";
          const fraction = fillFraction(state);
          return (
            <g key={id}>
              <path
                d={ridgePath(i)}
                fill="none"
                stroke="currentColor"
                strokeWidth={1.5}
                strokeLinecap="round"
                className="text-muted-foreground/20"
              />
              <motion.path
                d={ridgePath(i)}
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                strokeLinecap="round"
                className="text-primary"
                initial={false}
                animate={{ pathLength: fraction }}
                transition={
                  reduced
                    ? { duration: 0 }
                    : { duration: 0.7, delay: i * 0.05, ease: "easeOut" }
                }
              />
            </g>
          );
        })}
      </svg>
      <p className="text-xs text-muted-foreground" aria-live="polite">
        {filled} of {total} filled
      </p>
    </div>
  );
}
```

- [ ] **Step 3: Verify**

```bash
cd web && npm run build && npm run lint
```

- [ ] **Step 4: Commit**

```bash
git add web/lib/ridge-geometry.ts web/components/onboarding/fingerprint.tsx
git commit -m "feat(web): fingerprint component driven by real profile state"
```

---

### Task 3: Journey store, shell and dictation box

**Files:**
- Create: `web/components/onboarding/use-journey-store.ts`
- Create: `web/components/onboarding/journey-shell.tsx`
- Create: `web/components/onboarding/dictation-box.tsx`
- Create: `web/lib/sample-data.ts`

**Interfaces produced:**
- `useJourneyStore` — `{ chapter, notes, storyDrafts, keywords, sampleUsed, set*, reset }`, persisted to `localStorage` under `applination.journey.v1`.
- `<JourneyShell heading eyebrow onSkip onSample onBack onNext nextLabel busy>` — chapter frame.
- `<DictationBox value onChange onSettled placeholder minRows>` — autosaving textarea; `onSettled` fires 1200ms after the last keystroke.
- `SAMPLE` — per-chapter John Doe answers.

- [ ] **Step 1: Write the store**

Create `web/components/onboarding/use-journey-store.ts`:

```ts
"use client";

/**
 * In-flight journey state.
 *
 * Persisted to localStorage because a user who dictates for ninety seconds and
 * loses it to a reload will not do it twice. This is belt-and-braces: each
 * chapter also autosaves to the server.
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";

export type JourneyState = {
  chapter: number;
  notes: string;
  /** Titles of stories already told this session, for the "one more?" copy. */
  toldStories: string[];
  keywords: string[];
  /** Which chapters were filled from the sample, so we can mark them. */
  sampleUsed: string[];
  setChapter: (n: number) => void;
  setNotes: (s: string) => void;
  addToldStory: (title: string) => void;
  setKeywords: (k: string[]) => void;
  markSample: (chapter: string) => void;
  reset: () => void;
};

export const useJourneyStore = create<JourneyState>()(
  persist(
    (set) => ({
      chapter: 0,
      notes: "",
      toldStories: [],
      keywords: [],
      sampleUsed: [],
      setChapter: (n) => set({ chapter: n }),
      setNotes: (s) => set({ notes: s }),
      addToldStory: (title) =>
        set((s) => ({ toldStories: [...s.toldStories, title] })),
      setKeywords: (k) => set({ keywords: k }),
      markSample: (chapter) =>
        set((s) =>
          s.sampleUsed.includes(chapter)
            ? s
            : { sampleUsed: [...s.sampleUsed, chapter] },
        ),
      reset: () =>
        set({
          chapter: 0, notes: "", toldStories: [],
          keywords: [], sampleUsed: [],
        }),
    }),
    { name: "applination.journey.v1" },
  ),
);
```

- [ ] **Step 2: Write the sample data**

Create `web/lib/sample-data.ts`:

```ts
/**
 * Sample answers, for anyone who would rather look around than type.
 *
 * The persona is John Doe, the same fictional person as demo_data/. Kept as
 * frontend constants rather than served from the demo fixture: the fixture is a
 * full config + master_data tree, and reshaping it into chapter-sized snippets
 * would be more coupling than the reuse is worth.
 *
 * Anything filled from here MUST stay visibly marked — see sample-data-banner.
 */
export const SAMPLE = {
  notes:
    "I've been doing backend work for about four years, mostly Python and " +
    "Postgres. Last couple of years at a payments company where I looked " +
    "after the ledger service. Before that a smaller startup doing " +
    "everything from React to deploys.",
  story: {
    title: "The ledger migration",
    body:
      "We moved the ledger off a single Postgres box onto a partitioned " +
      "setup. The actual migration was fine — the annoying part was that " +
      "nobody could agree on what a 'transaction' meant across three teams, " +
      "so I spent more time in a room with a whiteboard than in the code. " +
      "Shipped it over a weekend with no downtime.",
  },
  contact: {
    full_name: "John Doe",
    email: "john.doe@example.com",
    phone: "+1 555 0100",
    location_city: "Seattle, WA",
  },
} as const;
```

- [ ] **Step 3: Write the shell**

Create `web/components/onboarding/journey-shell.tsx`:

```tsx
"use client";

/**
 * One chapter, full-bleed.
 *
 * Deliberately not a chat thread: the journey runs before the user has an API
 * key, so there is no model behind it. A scripted state machine wearing a chat
 * costume gets noticed within three turns and costs more trust than the old
 * wizard ever did. This frame is honest about being considered copy.
 */
import { ArrowLeft, ArrowRight, Loader2 } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";

export function JourneyShell({
  eyebrow,
  heading,
  children,
  onBack,
  onNext,
  onSkip,
  onSample,
  nextLabel = "Continue",
  busy = false,
}: {
  eyebrow?: string;
  heading: string;
  children: ReactNode;
  onBack?: () => void;
  onNext?: () => void;
  onSkip?: () => void;
  onSample?: () => void;
  nextLabel?: string;
  busy?: boolean;
}) {
  return (
    <section className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center gap-6 px-6 py-10">
      <header className="space-y-2">
        {eyebrow ? (
          <p className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
            {eyebrow}
          </p>
        ) : null}
        <h1 className="font-heading text-3xl font-extrabold tracking-tight sm:text-4xl">
          {heading}
        </h1>
      </header>

      <div className="space-y-4">{children}</div>

      <footer className="flex flex-wrap items-center gap-2 pt-2">
        {onBack ? (
          <Button variant="ghost" onClick={onBack} className="gap-2">
            <ArrowLeft className="size-4" /> Back
          </Button>
        ) : null}
        <div className="flex-1" />
        {onSample ? (
          <Button variant="ghost" size="sm" onClick={onSample}>
            Use a sample
          </Button>
        ) : null}
        {onSkip ? (
          <Button variant="ghost" size="sm" onClick={onSkip}>
            Skip this
          </Button>
        ) : null}
        {onNext ? (
          <Button onClick={onNext} disabled={busy} className="gap-2">
            {busy ? <Loader2 className="size-4 animate-spin" /> : null}
            {nextLabel} <ArrowRight className="size-4" />
          </Button>
        ) : null}
      </footer>
    </section>
  );
}
```

- [ ] **Step 4: Write the dictation box**

Create `web/components/onboarding/dictation-box.tsx`:

```tsx
"use client";

/**
 * A big, forgiving input sized for spoken-length answers.
 *
 * There is no microphone here on purpose. Voice arrives through the user's own
 * dictation tool (Wispr Flow, a phone keyboard mic, OS dictation) writing into
 * this textarea — which keeps every browser working, keeps audio off third
 * parties, and lets the privacy promise in chapter 1 stay literally true.
 *
 * "They paused" is therefore just a debounce on input, and behaves identically
 * whether the user typed or dictated.
 */
import { useEffect, useRef } from "react";

import { Textarea } from "@/components/ui/textarea";

const SETTLE_MS = 1200;

export function DictationBox({
  value,
  onChange,
  onSettled,
  placeholder,
  minRows = 6,
}: {
  value: string;
  onChange: (s: string) => void;
  onSettled?: (s: string) => void;
  placeholder?: string;
  minRows?: number;
}) {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latest = useRef(value);
  latest.current = value;

  useEffect(() => {
    if (!onSettled) return;
    if (timer.current) clearTimeout(timer.current);
    if (!value.trim()) return;
    timer.current = setTimeout(() => onSettled(latest.current), SETTLE_MS);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [value, onSettled]);

  return (
    <Textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      rows={minRows}
      className="min-h-40 text-base leading-relaxed"
    />
  );
}
```

- [ ] **Step 5: Verify and commit**

```bash
cd web && npm run build && npm run lint
git add web/components/onboarding web/lib/sample-data.ts
git commit -m "feat(web): journey store, chapter shell and dictation box"
```

---

### Task 4: Chapters 1–3 — the frame, just talk, follow the thread

**Files:**
- Create: `web/components/onboarding/chapters/01-frame.tsx`
- Create: `web/components/onboarding/chapters/02-talk.tsx`
- Create: `web/components/onboarding/chapters/03-thread.tsx`

**Copy is part of the spec, not decoration. Use it as written.**

**Chapter 1 — the frame.** Heading: *"Before we start."* Body, three short paragraphs:
1. "I help you find jobs worth applying to, then write the application. To do that well I need to know a bit about you."
2. "**I will never make anything up about you.** Nothing in a document I write will say something you didn't say first."
3. "Your files live on this machine, under `data/users/`. The whole thing is open source — you can read exactly what I do with them."
Then, plainly: *"None of this is required. You can skip anything, change everything later, and leave whenever you want."*
Buttons: `Start` (primary), `Just take me in` (ghost link → `/`).

**Chapter 2 — just talk.** Heading: *"So — what have you been working on lately?"*
- A `DictationBox`, placeholder: *"Whatever comes to mind. Ramble if you like — nobody's marking this."*
- Under it, a hint: *"Talking is easier than typing. If you have a dictation tool — Wispr Flow, or your phone's keyboard mic — use it."*
- A file drop, framed as an offer: *"Or drop your resume and I'll read it instead of making you type."*
- On settle → `api.saveIntakeNotes(value)`. On file → `api.parkIntakeResume(file)`.
- After a resume is parked, reflect back specifically: *"Got it — that's `{chars}` characters of resume parked. I'll turn it into something structured once you connect a provider."*

**Chapter 3 — follow the thread.** Heading: *"Which of these do you want to tell me about?"*
- Fetch `api.intakeThreads()`. Render each as a selectable chip, plus a final chip *"Something else"*.
- On pick, swap to a `DictationBox` with the heading *"{label} — what were you actually doing there?"* and placeholder *"How it went, what was annoying, what you'd do differently."*
- Save with `api.saveIntakeStory(label, body)`, then `addToldStory(label)`.
- Then: *"Anything else you want to tell me about?"* with the chips again, and a persistent ghost button *"That's enough for now"* → next chapter.
- If `threads` is empty: skip straight to the free-form prompt with heading *"Tell me about one thing you worked on."*

**Forbidden**: no chapter may use "proud", "challenge", "overcame", "strength", "weakness", or "accomplishment". Those produce rehearsed answers, which are useless as raw material.

- [ ] **Step 1: Write the three chapters**

Each is a client component taking `{ onNext, onBack }` and rendering `JourneyShell`. Use TanStack Query (`useQuery`/`useMutation`) as the rest of the app does, `toast` from `sonner` for errors, and the `useJourneyStore` for local state. Follow the patterns already in `web/app/onboarding/page.tsx` before it is rewritten — read it first for the established idioms.

- [ ] **Step 2: Verify**

```bash
cd web && npm run build && npm run lint
```

- [ ] **Step 3: Commit**

```bash
git add web/components/onboarding/chapters
git commit -m "feat(web): journey chapters 1-3, capture without a key"
```

---

### Task 5: Chapters 4–6 — search, payoff, ignition

**Files:**
- Create: `web/components/onboarding/chapters/04-search.tsx`
- Create: `web/components/onboarding/chapters/05-payoff.tsx`
- Create: `web/components/onboarding/chapters/06-ignition.tsx`

**Chapter 4 — "Here's what I think you're for."**
- Fetch `api.intakeSearchTerms()`. Render `keywords` as removable chips plus an add field.
- If `guessed`, the heading softens to *"I don't have much to go on yet — is this close?"* and a line: *"I'm guessing here. Change anything."* If not guessed: *"This is what I'd go looking for. Change anything that's wrong."*
- On continue: `PUT /api/onboarding/search` with the chips, **then** `api.startJobPreview()` before advancing, so the fetch overlaps the transition.

**Chapter 5 — the payoff.**
- Poll `api.jobPreview()` every 2s while `state === "running"` (TanStack Query `refetchInterval`).
- While running: *"Having a look at what's out there…"* with a skeleton.
- On ready: a `NumberTicker` on `total`, then *"{total} live roles right now, across {sources_total} boards. {matched} look like you."* Render `sample` as a scrollable list of real postings.
- If `sources_ok < sources_total`: append *"(across {sources_ok} of {sources_total} — a couple didn't answer)"*.
- On `error`: *"I couldn't reach the job boards just now — that's on me, not you. It'll work later."* and **still allow continue**. Chapter 5 never blocks.

**Chapter 6 — ignition.**
- Two panels. Contact fields (pre-filled from the store / sample where used), then provider choice from `api.providerSetup()`.
- Provider cards: recommended first, badge on it, `why` as the subtitle, `steps` as a three-item list, a primary button linking to `console_url` (target `_blank`, `rel="noopener noreferrer"`), the key input, and `cost_note` in muted text.
- If `stale`, show a muted line: *"These steps were checked on {verified_on} and may have moved — the link is the thing to trust."*
- Client-side key sanity check against `key_shape` before saving, so an obviously malformed key doesn't spend a real call.
- Save via `PUT /api/onboarding/user` and `PUT /api/onboarding/provider`, then run the cascade.

**The cascade** is the celebration, so build it carefully:
1. `api.enrichPlan()` → the ordered steps.
2. For each, in order: show its `label`, `await api.enrichStep(step.id)`, then invalidate the `profileStrength` query so the fingerprint re-reads real state and the ridge fills.
3. On a step failure: show the error inline with a **Retry** button for that step alone, and a **Skip** that moves to the next. Never abandon the whole cascade.
4. When done: `POST /api/onboarding/complete`, then route to `/`.

- [ ] **Step 1: Write the three chapters**
- [ ] **Step 2: Verify**

```bash
cd web && npm run build && npm run lint
```

- [ ] **Step 3: Commit**

```bash
git add web/components/onboarding/chapters
git commit -m "feat(web): journey chapters 4-6, payoff and the enrichment cascade"
```

---

### Task 6: Wire it up — router, dashboard card, sample marking

**Files:**
- Rewrite: `web/app/onboarding/page.tsx`
- Create: `web/components/profile-strength-card.tsx`
- Create: `web/components/sample-data-banner.tsx`
- Modify: `web/app/page.tsx` (mount both)
- Modify: `server/onboarding.py` (two small routes — see below)
- Test: `tests/test_sample_marker.py`

**Backend addition.** The banner has to survive a reload and a different browser, so "this account contains sample data" is server state, not `localStorage`:

- `POST /api/onboarding/sample-used` — body `{"used": true}` → sets `Setting(user_id, "sample_data_used")`.
- `DELETE /api/onboarding/sample-used` → clears the flag.
- `GET /api/onboarding/status` gains `"sample_data": bool`.

Wiping is deliberately **not** automated: the banner links to `/config` and `/master-data` and says *"Sample values are still in your profile — replace them before you run."* Deleting a user's master data from a banner click is the kind of irreversible action that needs a real confirmation flow, and it is out of scope here. **This is a deviation from the spec's "one-click wipe"; flag it to the user rather than quietly shipping either version.**

- [ ] **Step 1: Add the backend routes and status field**

In `server/onboarding.py`, add to `_compute_status`'s returned dict:

```python
        "sample_data": _get_setting(user_id, "sample_data_used") == "1",
```

and the routes:

```python
class SampleUsedBody(BaseModel):
    used: bool = True


@router.post("/sample-used")
def set_sample_used(
    body: SampleUsedBody, user: User = Depends(require_user)
) -> dict:
    """Record that this account holds sample values.

    Server state, not localStorage: the warning has to survive a reload and
    follow the account to another browser. Sample data quietly becoming
    somebody's real cover letter is the failure this exists to prevent.
    """
    _set_setting(user.id, "sample_data_used", "1" if body.used else "0")
    return {"ok": True, **_compute_status(user)}


@router.delete("/sample-used")
def clear_sample_used(user: User = Depends(require_user)) -> dict:
    _set_setting(user.id, "sample_data_used", "0")
    return {"ok": True, **_compute_status(user)}
```

- [ ] **Step 2: Write the backend test**

Create `tests/test_sample_marker.py`:

```python
"""The sample-data marker.

Sample values silently becoming a real cover letter is the most likely way the
"use a sample" affordance turns into a bug report, so the marking is part of the
feature rather than polish on it.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server.db as db

from .conftest import make_engine, register


@pytest.fixture()
def client(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, "engine", engine)
    from server.app import app

    with TestClient(app) as c:
        register(c, "a@example.com")
        yield c


def test_status_starts_without_the_sample_flag(client):
    assert client.get("/api/onboarding/status").json()["sample_data"] is False


def test_marking_sample_data_persists(client):
    client.post("/api/onboarding/sample-used", json={"used": True})
    assert client.get("/api/onboarding/status").json()["sample_data"] is True


def test_clearing_the_marker_works(client):
    client.post("/api/onboarding/sample-used", json={"used": True})
    client.delete("/api/onboarding/sample-used")
    assert client.get("/api/onboarding/status").json()["sample_data"] is False


def test_the_marker_is_per_user(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, "engine", engine)
    from server.app import app

    with TestClient(app) as ca, TestClient(app) as cb:
        register(ca, "a@example.com")
        register(cb, "b@example.com")
        ca.post("/api/onboarding/sample-used", json={"used": True})
        assert cb.get("/api/onboarding/status").json()["sample_data"] is False
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_sample_marker.py -q`
Expected: 4 passed

- [ ] **Step 3: Rewrite the page as a thin router**

`web/app/onboarding/page.tsx` keeps only: the chapter index from `useJourneyStore`, the `<Fingerprint>` pinned top-right (fed by `useQuery(["profileStrength"], api.profileStrength)`), and a switch rendering chapters 1–6.

- [ ] **Step 4: Write the dashboard card and banner**

`profile-strength-card.tsx`: the fingerprint, `next.label` + `next.hint` as the single call to action during `formation`; during `depth`, the coverage sentence — *"Your stories cover {covered}. Nothing yet for {gaps} — roles tagged that way will get a weaker letter."*

`sample-data-banner.tsx`: renders only when `status.sample_data` is true. Amber, dismissible-per-session but never permanently, links to `/master-data` and `/config`.

Mount both in `web/app/page.tsx`.

- [ ] **Step 5: Verify everything**

```bash
cd web && npm run build && npm run lint
cd .. && .venv/Scripts/python.exe -m pytest tests/ -q
```
Expected: clean build, clean lint, all Python tests pass.

- [ ] **Step 6: Commit**

```bash
git add web server/onboarding.py tests/test_sample_marker.py
git commit -m "feat: mount the journey, dashboard fingerprint and sample marker"
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| Six chapters in the specified order | 4, 5 |
| Chapter 1 states the anti-fabrication promise + data location | 4 |
| Resume optional, offered inside the conversation | 4 |
| Friend-register questions, no interview questions | 4 (enforced by the forbidden-words constraint) |
| Threads picked by the user from their own words | 4 |
| Search terms derived and offered for correction, last | 5 |
| Live job payoff, degrades gracefully, never blocks | 5 |
| Contact + key together as ignition | 5 |
| Enrichment cascade drives ridge fill, per-step retry | 5 |
| Fingerprint permanent on the dashboard | 6 |
| Depth phase shows coverage | 6 |
| Everything skippable, stated in chapter 1 | 3, 4 |
| Sample data visibly marked | 6 |
| Reduced motion, aria-live, text counter | 2 |

**Deviations from the spec, both needing a decision rather than silent shipping:**

1. **Sample data lives in `web/lib/sample-data.ts`, not `demo_data/`.** The fixture is a whole config + master_data tree; reshaping it into chapter-sized snippets would be more coupling than the reuse is worth. Same fictional persona either way.
2. **No one-click wipe.** The banner points at `/master-data` and `/config` instead. Deleting a user's master data from a banner click needs a real confirmation flow, which is its own piece of work.

**Weaker verification than plans 1–2, by design:** frontend is checked with build + lint only, per the project's standing preference. Logic worth testing was pushed into `ridge-geometry.ts` and `sample-data.ts`; the components are thin on purpose so that there is little behaviour hiding where tests cannot see it.
