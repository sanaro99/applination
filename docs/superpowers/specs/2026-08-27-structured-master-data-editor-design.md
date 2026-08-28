# Structured master-data editor — design

**Date:** 2026-08-27
**Status:** proposed
**Issue:** [#56](https://github.com/sanaro99/applination/issues/56)
**Replaces:** the raw-YAML textarea on the `/master-data` resume tab
**Depends on:** [#57](https://github.com/sanaro99/applination/pull/57) — `src/master_resume.py` and one canonical shape for `skills`

## Why

`/master-data` hands the user a `<Textarea>` containing `resume.yaml`. Not a code
editor — a plain textarea with a monospace font, no highlighting, no structure.

That file is deliberately the "everything file": the shipped template is 95 lines
before anyone fills it in, and a real one is longer, because `bullets_all` is
meant to hold every bullet the tailor can choose from. So the first thing a new
user sees after onboarding is a long file where they must work out for
themselves that indentation is load-bearing, that a two-space slip silently
changes meaning, when a value needs quoting, and which of the top-level keys
matter. There is no visual separation between "your jobs" and "your skills". A
user cannot find the part they want to change, and cannot tell whether their
edit is structurally valid until they press Save.

The AI-assist panel reliably produces valid YAML, so the AI path is fine. The gap
is direct editing — the common case for a small fix like correcting a job title
or adding one bullet.

A second gap sits alongside it: after any edit, AI or human, the only feedback is
the words `· unsaved changes`. The user is asked to approve a change they cannot
see.

## Scope

This is the first of three specs. "Everything editable" is three different design
problems, and one document covering all three would either stay too abstract to
implement from or grow too long to review:

| spec | surface | what it is | form vocabulary |
| --- | --- | --- | --- |
| **1 (this one)** | `resume.yaml` | content — your history | entry cards, bullet lists, reordering |
| 2 | stories, `bio.md` | classification — how work gets matched | tag pickers bound to the taxonomy |
| 3 | `config.yaml` | settings — how the run behaves | toggles, numbers, source checkboxes |

Spec 1 builds the machinery the other two reuse. It also absorbs the change-review
work, so "what changed" is defined once for both text edits and structured field
edits rather than twice.

Out of scope here: stories, `bio.md`, `config.yaml`, and the `Target roles` tab.

## Settled decisions

Decided during brainstorming. Inputs, not open questions.

1. **The server owns the YAML.** The form speaks JSON to structured endpoints;
   YAML is never generated in a browser. The alternative — parsing and
   serialising YAML client-side against the existing text endpoint — needs no
   backend work but duplicates the schema in TypeScript and demotes
   `MASTER_RESUME_SCHEMA` from source of truth to "the thing the LLM uses".
2. **Whole-document save, not per-section.** One `PUT` of the whole structured
   document. Section-level endpoints would guard against a concurrency problem
   that does not exist: one user editing their own file.
3. **The raw YAML view survives**, behind an `Advanced` sub-tab, still editable.
   It is the escape hatch for anything the form does not model.
4. **The schema drives validation, not rendering.** Auto-generating a form from
   JSON Schema is how you end up with `ats_adjacent_skills` as a visible label
   and a bare string-array widget for bullets. Section components are hand-built.
5. **`MASTER_RESUME_SCHEMA` is unchanged.** It stays the wire format for the LLM
   import.
6. **Vitest is added for `web/lib` pure functions only.** No component or DOM
   testing. See *Testing*.

## Architecture

Three layers, each understandable without reading the others.

```
web/components/master-data/          the form, one file per section
        │  JSON
        ▼
server/master_data.py                every master-data endpoint
        │  dict
        ▼
src/master_resume.py                 all YAML knowledge for this file
        │
        ▼
data/users/<id>/master_data/resume.yaml
```

`src/` still imports nothing from `server/`, as today.

### `src/master_resume.py` — gains `render_master`

```python
def render_master(existing_text: str, data: dict) -> str
```

Reads `existing_text` with ruamel's round-trip loader, replaces only the
top-level keys the form owns, and leaves everything else intact: comments, key
order, and any key the schema does not model. Returns the rendered YAML.

"The keys the form owns" means exactly the eight in `_MASTER_RESUME_KEYS`
(`content_studio.py`): `profile`, `summary_options`, `core_skills`,
`ats_adjacent_skills`, `skills`, `experience`, `projects`, `education`. A key
absent from `data` but present in the file is left alone rather than deleted —
the form must never remove something it does not render.

The module already owns `load_master` / `normalize_master` / `normalize_skills`
from #57, so read and write knowledge for this file stay in one place.

**On comments.** `UserPaths.ensure()` seeds only `config.yaml` from its template;
`resume.yaml` is written by the AI import via `yaml.safe_dump` with a two-line
header. So a real user's file has almost no comments today, and a plain rewrite
would be nearly lossless. Round-tripping anyway is cheap, and the `Advanced` tab
means a user *can* add comments — silently deleting them would be data loss in a
file holding someone's career history. Spec 3 needs the same machinery for
`config.yaml`, which *is* seeded from a heavily commented template.

### `server/master_data.py` — new router

Every master-data endpoint moves here. The text `GET`/`PUT` handlers currently in
`config_api.py` move unchanged, at the **same URLs**, so nothing client-side
breaks and "how master data is served" becomes one file. `config_api.py` keeps
`config.yaml` and secrets.

This is a targeted improvement to code the work already touches, not unrelated
refactoring: adding structured endpoints to `config_api.py` would mix two
resources in a file that is already doing two jobs.

| endpoint | method | body / returns |
| --- | --- | --- |
| `/api/master-data/resume/structured` | `GET` | `{"data": <normalized master dict>}` |
| `/api/master-data/resume/structured` | `PUT` | `{"data": {...}}` → `{"ok": true}` |
| `/api/master-data/resume` | `GET`/`PUT` | unchanged raw text |
| `/api/master-data/bio`, `/stories/*` | — | unchanged, moved file only |

`GET` returns `load_master(paths.resume_path)`, so a file still in the old
list-shaped `skills` form is normalized on the way out and #57 keeps holding.

`PUT` validates `data` against `MASTER_RESUME_SCHEMA` using `jsonschema` (already
a dependency), then writes `render_master(current_text, data)`.

**Validation errors must name the field.** A raw `jsonschema` message is not
usable by the audience this feature exists for. The handler translates the
error's path into `experience[1].company is required` and returns 400 with that.

**Tolerant on read, strict on write.** The form renders whatever it finds,
including a half-finished or slightly wrong file, and refuses to *save* anything
the schema rejects. The text `PUT` deliberately stays permissive — it only checks
that the input parses as YAML — because an escape hatch that enforces the schema
is not an escape hatch.

Both endpoints are per-user via `paths_for(user)` and carry `require_user`. No DB
queries, so `server/scoping.py` does not apply and no `# noscope:` marker is
needed.

## The form

`web/app/master-data/page.tsx` is 554 lines. Eight section editors would put it
well past the size where edits stay reliable — the same judgement already
recorded in `app/onboarding/page.tsx`, whose docstring names its 795-line
predecessor as the reason it was split. So the page becomes a thin tab router and
the sections live in `web/components/master-data/`.

Sections appear in file order. Each is a collapsible card with a plain-language
title, a one-line reason it matters, and a summary in its header when collapsed
(`Jobs you've had — 2 jobs`).

| key | shown as | control |
| --- | --- | --- |
| `profile` | Who you are | identity titles (tag input), seniority (select) |
| `summary_options` | How you describe yourself | list of textareas |
| `core_skills` | Skills you always list | tag input |
| `ats_adjacent_skills` | Skills to add when a job asks | tag input |
| `skills` | Skill groups | group name + items, mapping-shaped per #57 |
| `experience` | Jobs you've had | entry cards |
| `projects` | Projects | entry cards |
| `education` | Education | entry cards |

An entry card holds its own fields (company / role / location / start / end) and
its bullets as individual textareas. Entries and bullets both support add,
remove and reorder via `@dnd-kit/sortable` — already a dependency, already used
by `applications-kanban.tsx`.

One **Save** for the document, with a single dirty state. Sections collapse for
navigation, not for saving.

### Copy

Labels name what the user controls, not how the file is keyed: "Jobs you've had",
not `experience`. Each section carries one line on why it matters — that is where
the template's comments go. They were scaffolding for reading raw YAML, and a
form is a better home for the same information.

## Change review

Replaces the bare `· unsaved changes` with a count and a reviewable panel.

One renderer, `web/components/change-review.tsx`, taking `DiffLine[]`. Two
producers:

- **Text surfaces** — bio, stories, `Advanced` YAML:
  `diffLines(before.split("\n"), after.split("\n"))`. `diffLines` already exists
  in `web/lib/resume-diff.ts`.
- **The resume form** — a new `flattenMaster(data)` in `web/lib/master-flatten.ts`
  producing labeled lines (`§ Jobs — Software Engineer @ Example Corp`,
  `• bullet…`), fed through the same `diffLines`. This mirrors `flattenResume`,
  which already does exactly this for the *tailored* resume shape on application
  detail. `flattenResume` targets the tailored schema and is not reusable here,
  but the pattern is proven and in production.

Because both paths end in `DiffLine[]`, an AI rewrite and a hand edit are
reported identically, and Save can state what it will do instead of merely that
something happened. `AiAssist`'s existing "Draft updated — review and Save" toast
becomes true rather than aspirational.

It appears in two places: `TextEditor`'s header row, replacing the amber text,
and the form's save bar.

## Testing

**Python** — covers the real risk:

- schema validation accepts a valid document and rejects an invalid one
- a validation failure reports a usable field path, not a raw validator dump
- `render_master` preserves comments, unknown keys and key order
- structured `GET` → `PUT` → `GET` round-trips to an equal dict, and a no-op save
  neither reorders nor drops keys (byte equality is *not* asserted: the file on
  disk was written by `yaml.safe_dump` and ruamel may legitimately requote or
  rewrap it)
- a file with list-shaped `skills` still normalizes on `GET` (guards #57)
- the text `PUT` and the structured `PUT` agree on the same file
- both endpoints 401 without a session, and read only the calling user's tree

**Frontend** — `web/` has no test runner; `package.json` carries only
dev/build/start/lint, and the project convention is build + lint with the user
checking visuals.

This spec adds **vitest as a dev dependency, scoped to pure functions in
`web/lib`**. No component rendering, no DOM, no change to the build. The
justification is narrow: `flattenMaster` and `diffLines` are pure functions whose
failure mode is showing the user a *false* account of what they are about to
save, which is worse than showing nothing. Cases that matter:

- an entry deleted from the middle of a list
- a reorder, which must not read as a wholesale add plus remove
- a section emptied entirely
- a no-op producing zero changes

The visual convention is untouched; this tests logic, not appearance.

## Risks

- **The two views can disagree.** The form and the `Advanced` tab write the same
  file. Switching tabs must re-read from the server rather than trusting cached
  state, or one view will save over the other's work. Both tabs invalidate the
  same TanStack Query keys on save.
- **Reorder diffs are the hard case.** A naive line diff reports a moved bullet
  as one removal plus one addition. That is not wrong, but it is noisy. Acceptable
  for v1; the vitest case above pins the behaviour so a later improvement is a
  deliberate change rather than a surprise.
- **Schema drift between Python and TypeScript.** The form's TS types are
  hand-written against `MASTER_RESUME_SCHEMA`. Server-side validation is what
  actually enforces the contract, so drift produces a clear 400 rather than a
  corrupt file.

## Out of scope

Stories and `bio.md` (spec 2), `config.yaml` (spec 3), the `Target roles` tab,
any change to `MASTER_RESUME_SCHEMA`, and component-level frontend tests.
