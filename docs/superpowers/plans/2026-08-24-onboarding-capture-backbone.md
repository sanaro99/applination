# Onboarding Capture Backbone — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the backend everything it needs to capture a new user's raw material — freeform notes, a parked resume, verbatim draft stories — and to derive conversation chips from it, using **zero LLM calls**.

**Architecture:** A new per-user `_intake/` directory under `master_data/`, owned by `UserPaths`, holds raw captured material. A new pure module `src/intake_extract.py` derives chips deterministically from that text using the tag taxonomy already committed in `master_data/stories/_INDEX.md` and the Greenhouse company list already in `src/scrapers/greenhouse_companies.py`. Thin endpoints on the existing authenticated `/api/onboarding` router expose both. Nothing here calls a provider, so every endpoint works before a user has an API key.

**Tech Stack:** Python 3, FastAPI, SQLModel, pytest, `fastapi.testclient.TestClient`.

**Spec:** `docs/superpowers/specs/2026-08-24-onboarding-journey-design.md`

## Plan set

This is **plan 1 of 3**. The spec covers three independently shippable subsystems:

1. **Capture backbone (this plan)** — intake storage, deterministic extraction, intake endpoints. Ships working software: the backend can capture everything a journey collects, with no key.
2. **Enrichment, payoff and strength** — `POST /preview-jobs` (chapter 5's live job counts), the `enrich/plan` + `enrich/step` cascade, `server/profile_strength.py`, `server/provider_setup.py`.
3. **The journey UI** — the six chapters, the fingerprint component, the journey store, sample-fill.

Plan 3 depends on 1 and 2. Plan 2 depends on 1.

## Global Constraints

Copied verbatim from the spec; every task's requirements implicitly include these.

- **No LLM call may happen anywhere in this plan.** Capture must work before a provider key exists. If a test needs a provider to pass, the implementation is wrong.
- **Never join a path onto `data/users` by hand.** `server/user_paths.resolve_within` is the containment guard and only works as the single door.
- **Every DB query against a tenant table** must go through `server/scoping.py` (`owned` / `get_owned` / `find_owned`) or carry an explicit `# noscope: <reason>`. `tests/test_scope_lint.py` fails the build otherwise. *(This plan adds no new DB queries; the constraint is stated so it is not violated by accident.)*
- **Extraction is precision-biased.** "Showing four good chips beats showing eight with two absurd ones."
- **Draft stories must never be counted as real stories** by `reference_loader` or `onboarding._count_stories`.
- **Drafts are moved, never deleted** — `_intake/consumed/` exists so a failed enrichment cannot destroy the user's own words.
- Tests run against SQLite via the real Alembic migrations (`tests/conftest.py:migrate`); `isolated_user_data` is autouse and redirects `user_paths.USERS_DIR` to a tmp dir.

---

## File Structure

| File | Responsibility |
|---|---|
| `server/user_paths.py` *(modify)* | Add the `_intake/` tree to the path layout and to `ensure()`. |
| `src/intake_extract.py` *(create)* | Pure, LLM-free derivation of chips from text. No I/O, no imports from `server/`. |
| `server/intake.py` *(create)* | Read/write the intake tree. Slugging, frontmatter, collision handling, containment. |
| `server/onboarding.py` *(modify)* | Six thin endpoints wiring the two modules to HTTP, plus the `intake` block on `/status`. |
| `tests/test_intake_paths.py` *(create)* | The intake tree exists, and is invisible to the real stories dir. |
| `tests/test_intake_extract.py` *(create)* | The bulk of the value — pure-function tests of vocabulary, threads, search terms. |
| `tests/test_intake_storage.py` *(create)* | Slugging, collisions, frontmatter, path containment. |
| `tests/test_intake_api.py` *(create)* | Endpoint behaviour, including "works with no API key configured". |

`src/intake_extract.py` takes its vocabulary and company list as **parameters**, not imports, so it stays pure and trivially testable. `server/intake.py` is the only module that knows where the files live.

---

### Task 1: Intake paths on `UserPaths`

**Files:**
- Modify: `server/user_paths.py:87` (after `stories_dir`) and `server/user_paths.py:115` (`ensure`)
- Test: `tests/test_intake_paths.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `UserPaths.intake_dir`, `.intake_stories_dir`, `.intake_consumed_dir`, `.intake_resume_path`, `.intake_notes_path` — all `Path`. `ensure()` creates the directories.

- [ ] **Step 1: Write the failing test**

Create `tests/test_intake_paths.py`:

```python
"""The _intake tree: where raw captured material lives before enrichment.

It sits under master_data/ but outside stories/, because reference_loader and
onboarding._count_stories glob stories/*.md — a draft landing there would be
matched into a real cover letter.
"""
from __future__ import annotations

from server.user_paths import UserPaths


def test_ensure_creates_the_intake_tree():
    paths = UserPaths(user_id=1).ensure()
    assert paths.intake_dir.is_dir()
    assert paths.intake_stories_dir.is_dir()
    assert paths.intake_consumed_dir.is_dir()


def test_ensure_is_idempotent():
    UserPaths(user_id=1).ensure()
    paths = UserPaths(user_id=1).ensure()
    assert paths.intake_stories_dir.is_dir()


def test_intake_files_sit_inside_intake_dir():
    paths = UserPaths(user_id=1)
    assert paths.intake_resume_path.parent == paths.intake_dir
    assert paths.intake_notes_path.parent == paths.intake_dir


def test_drafts_are_invisible_to_the_real_stories_glob():
    paths = UserPaths(user_id=1).ensure()
    (paths.intake_stories_dir / "a-draft.md").write_text("draft", encoding="utf-8")
    real = [p for p in paths.stories_dir.glob("*.md") if not p.name.startswith("_")]
    assert real == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_intake_paths.py -v`
Expected: FAIL with `AttributeError: 'UserPaths' object has no attribute 'intake_dir'`

- [ ] **Step 3: Write minimal implementation**

In `server/user_paths.py`, add after the `stories_dir` property:

```python
    @cached_property
    def intake_dir(self) -> Path:
        """Raw material captured during onboarding, before any LLM has touched
        it. Underscore-prefixed like ``stories/_INDEX.md``, and deliberately
        *outside* ``stories/``: ``reference_loader`` and
        ``onboarding._count_stories`` glob ``stories/*.md``, so a draft parked
        there would be matched into a real cover letter as though the user had
        written and approved it."""
        return self.master_dir / "_intake"

    @cached_property
    def intake_stories_dir(self) -> Path:
        return self.intake_dir / "stories"

    @cached_property
    def intake_consumed_dir(self) -> Path:
        """Drafts are moved here after enrichment rather than deleted, so a
        failed or unsatisfying enrichment never destroys the user's own words."""
        return self.intake_dir / "consumed"

    @cached_property
    def intake_resume_path(self) -> Path:
        return self.intake_dir / "resume_raw.txt"

    @cached_property
    def intake_notes_path(self) -> Path:
        return self.intake_dir / "notes.md"
```

In `ensure()`, extend the directory tuple:

```python
        for d in (
            self.master_dir,
            self.stories_dir,
            self.cover_letter_examples_dir,
            self.default_output_dir,
            self.intake_stories_dir,
            self.intake_consumed_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)
```

`intake_dir` itself needs no entry — `mkdir(parents=True)` on its children creates it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_intake_paths.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add server/user_paths.py tests/test_intake_paths.py
git commit -m "feat: add per-user _intake tree for raw onboarding material"
```

---

### Task 2: Tag-taxonomy vocabulary loader

**Files:**
- Create: `src/intake_extract.py`
- Test: `tests/test_intake_extract.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `load_vocabulary(index_md: str) -> set[str]` — parses the `## Tag taxonomy` section of a `stories/_INDEX.md` document into a set of lowercase tags.

Why parse the committed taxonomy rather than hardcode a word list: extraction and `reference_loader.match_stories()` then use the *same* vocabulary, so a chip the user picks is a tag that can actually match a job later.

- [ ] **Step 1: Write the failing test**

Create `tests/test_intake_extract.py`:

```python
"""Deterministic, LLM-free extraction of conversation chips.

Precision over recall throughout: four good chips beat eight with two absurd
ones, because the user sees these as "things you mentioned" and a wrong one
reads as the product not having listened.
"""
from __future__ import annotations

from src.intake_extract import load_vocabulary

SAMPLE_INDEX = """# Stories Index

Prose that must not become vocabulary.

## Tag taxonomy (expand as needed)

**Technical areas:** ai, llm, rag, backend, platform,
devtools, security

**Specific tech:** python, typescript, fastapi

**Role types (role_fit):** swe, ml-engineer, sre
"""


def test_reads_comma_lists_including_continuation_lines():
    vocab = load_vocabulary(SAMPLE_INDEX)
    assert {"ai", "llm", "rag", "backend", "platform", "devtools", "security"} <= vocab
    assert {"python", "typescript", "fastapi"} <= vocab
    assert {"swe", "ml-engineer", "sre"} <= vocab


def test_ignores_prose_outside_the_taxonomy_section():
    vocab = load_vocabulary(SAMPLE_INDEX)
    assert "prose" not in vocab
    assert "vocabulary" not in vocab


def test_ignores_the_headings_own_parenthetical():
    vocab = load_vocabulary(SAMPLE_INDEX)
    assert "expand" not in vocab
    assert "needed" not in vocab


def test_ignores_the_bold_label_text_itself():
    vocab = load_vocabulary(SAMPLE_INDEX)
    assert "technical" not in vocab
    assert "areas" not in vocab
    assert "role_fit" not in vocab


def test_missing_taxonomy_section_yields_empty_set():
    assert load_vocabulary("# Stories Index\n\nNo taxonomy here.\n") == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_intake_extract.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.intake_extract'`

- [ ] **Step 3: Write minimal implementation**

Create `src/intake_extract.py`:

```python
"""Deterministic derivation of conversation chips from a user's own words.

Pure functions only: no I/O, no LLM, no imports from ``server``. The onboarding
journey runs before the user has an API key, so everything here must work with
nothing but text.

The vocabulary and company list are passed in rather than imported so these
functions stay trivially testable and the caller owns the I/O.
"""
from __future__ import annotations

import re

# A tag is lowercase, starts with a letter, and may contain digits, hyphens,
# dots or plus signs (c++, node.js, ml-engineer). Two characters minimum, since
# real tags like "ai" and "ml" are that short.
_TAG = re.compile(r"^[a-z][a-z0-9.+-]{1,29}$")


def load_vocabulary(index_md: str) -> set[str]:
    """Parse the ``## Tag taxonomy`` section of a stories ``_INDEX.md``.

    The section is a series of ``**Label:** a, b, c`` lines whose lists may wrap
    onto following lines. Only those payloads are read: prose elsewhere in the
    file, the bold labels themselves, and the heading's own parenthetical are
    all excluded, because any of them becoming a "tag" would surface as a
    nonsense chip in front of the user.
    """
    _, _, tail = index_md.partition("## Tag taxonomy")
    if not tail:
        return set()

    payloads: list[str] = []
    capturing = False
    for line in tail.splitlines():
        stripped = line.strip()
        if ":**" in stripped:
            capturing = True
            payloads.append(stripped.split(":**", 1)[1])
            continue
        if not stripped:
            capturing = False
            continue
        if capturing:
            payloads.append(stripped)

    vocab: set[str] = set()
    for chunk in payloads:
        chunk = re.sub(r"\([^)]*\)", " ", chunk)
        for raw in chunk.split(","):
            token = raw.strip().strip(".").lower()
            if _TAG.match(token):
                vocab.add(token)
    return vocab
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_intake_extract.py -v`
Expected: 5 passed

- [ ] **Step 5: Verify against the real committed taxonomy**

Run:

```bash
python -c "from pathlib import Path; from src.intake_extract import load_vocabulary; v = load_vocabulary(Path('master_data/stories/_INDEX.md').read_text(encoding='utf-8')); print(len(v)); print(sorted(v)[:25])"
```

Expected: a count comfortably above 40, and a first-25 listing containing recognisable tags (`ai`, `accessibility`, `aws`, `backend`, …) and **no** English prose words. If prose appears, tighten the parser before continuing — a bad vocabulary poisons every chip in Task 3.

- [ ] **Step 6: Commit**

```bash
git add src/intake_extract.py tests/test_intake_extract.py
git commit -m "feat: parse the committed tag taxonomy into an extraction vocabulary"
```

---

### Task 3: `extract_threads` — chips for chapter 3

**Files:**
- Modify: `src/intake_extract.py`
- Test: `tests/test_intake_extract.py`

**Interfaces:**
- Consumes: `load_vocabulary` from Task 2.
- Produces:
  - `Thread` — frozen dataclass with `label: str` and `kind: str` (one of `"company"`, `"topic"`, `"phrase"`).
  - `extract_threads(text: str, resume_text: str = "", *, vocabulary: set[str] | None = None, companies: Sequence[str] = (), limit: int = 8) -> list[Thread]`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_intake_extract.py`:

```python
from src.intake_extract import Thread, extract_threads


def test_finds_a_known_company_by_name():
    threads = extract_threads("I was at Stripe for two years", companies=["stripe"])
    assert Thread(label="Stripe", kind="company") in threads


def test_finds_vocabulary_topics():
    threads = extract_threads(
        "mostly backend work, a lot of python",
        vocabulary={"backend", "python", "frontend"},
    )
    labels = [t.label for t in threads]
    assert "backend" in labels
    assert "python" in labels
    assert "frontend" not in labels


def test_finds_verb_anchored_phrases():
    threads = extract_threads("I built the payments migration last year")
    assert Thread(label="payments migration", kind="phrase") in threads


def test_phrases_stop_at_two_words_so_they_do_not_swallow_the_sentence():
    threads = extract_threads("I built the payments migration last year")
    assert all("last year" not in t.label for t in threads)


def test_corporate_noise_is_dropped():
    threads = extract_threads("I worked on Inc and shipped Ltd")
    assert [t for t in threads if t.label.lower() in {"inc", "ltd"}] == []


def test_duplicates_are_collapsed_case_insensitively():
    threads = extract_threads(
        "python, Python, PYTHON everywhere", vocabulary={"python"}
    )
    assert len([t for t in threads if t.label.lower() == "python"]) == 1


def test_result_is_capped():
    vocab = {f"tag{i}" for i in range(30)}
    text = " ".join(sorted(vocab))
    assert len(extract_threads(text, vocabulary=vocab, limit=8)) == 8


def test_reads_the_resume_as_well_as_the_typed_text():
    threads = extract_threads("", resume_text="Senior Engineer, Figma", companies=["figma"])
    assert Thread(label="Figma", kind="company") in threads


def test_empty_input_yields_no_chips():
    assert extract_threads("") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_intake_extract.py -v`
Expected: FAIL with `ImportError: cannot import name 'Thread' from 'src.intake_extract'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/intake_extract.py`:

```python
from collections.abc import Sequence
from dataclasses import dataclass

# Words that are technically nouns in the right place but always read as noise
# in a chip: the user sees "things you mentioned", and "Inc" is not one.
_STOPLIST = frozenset(
    {
        "inc", "ltd", "llc", "corp", "corporation", "technologies", "technology",
        "solutions", "systems", "services", "group", "company", "team", "the",
        "and", "stuff", "things", "work",
    }
)

# Deliberately conservative: at most two words after the verb. Three would let
# "built the payments migration last year" capture "last year" too, and a chip
# the user did not say is worse than a chip we failed to offer.
_VERB_ANCHOR = re.compile(
    r"\b(?:worked\s+on|built|led|shipped|migrated|designed|launched|ran)\s+"
    r"(?:the\s+|a\s+|an\s+)?"
    r"(?P<obj>[A-Za-z][\w-]*(?:\s+[A-Za-z][\w-]*)?)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Thread:
    """One concrete thing the user mentioned, offered back for them to expand."""

    label: str
    kind: str  # "company" | "topic" | "phrase"


def _dedupe(threads: list[Thread]) -> list[Thread]:
    seen: set[str] = set()
    out: list[Thread] = []
    for thread in threads:
        key = thread.label.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(thread)
    return out


def extract_threads(
    text: str,
    resume_text: str = "",
    *,
    vocabulary: set[str] | None = None,
    companies: Sequence[str] = (),
    limit: int = 8,
) -> list[Thread]:
    """Concrete things the user mentioned, most confident first.

    Order is confidence order — a named company is a surer thing to ask about
    than a verb-anchored phrase — and the cap then keeps the best ones.
    """
    haystack = f"{text}\n{resume_text}"
    low = haystack.lower()
    found: list[Thread] = []

    for slug in companies:
        if slug.lower() in _STOPLIST:
            continue
        if re.search(rf"\b{re.escape(slug.lower())}\b", low):
            found.append(Thread(label=slug.title(), kind="company"))

    for term in sorted(vocabulary or set()):
        if term in _STOPLIST:
            continue
        if re.search(rf"\b{re.escape(term)}\b", low):
            found.append(Thread(label=term, kind="topic"))

    for match in _VERB_ANCHOR.finditer(haystack):
        obj = " ".join(match.group("obj").split()).strip(" .,;:")
        if len(obj) < 3 or obj.lower() in _STOPLIST:
            continue
        if all(word.lower() in _STOPLIST for word in obj.split()):
            continue
        found.append(Thread(label=obj, kind="phrase"))

    return _dedupe(found)[:limit]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_intake_extract.py -v`
Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add src/intake_extract.py tests/test_intake_extract.py
git commit -m "feat: derive conversation chips from the user's own words"
```

---

### Task 4: `extract_search_terms` — chips for chapter 4

**Files:**
- Modify: `src/intake_extract.py`
- Test: `tests/test_intake_extract.py`

**Interfaces:**
- Consumes: `load_vocabulary` from Task 2; `_STOPLIST` and the `dataclass`/`re` imports established in Task 3 (same module, appended below them).
- Produces:
  - `SearchTerms` — frozen dataclass with `keywords: tuple[str, ...]` and `guessed: bool`.
  - `extract_search_terms(text: str, resume_text: str = "", *, vocabulary: set[str] | None = None, limit: int = 6) -> SearchTerms`

`guessed=True` means nothing was found and defaults were substituted; the UI uses it to hedge its copy ("I'm guessing here — fix this") instead of presenting invented confidence as fact.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_intake_extract.py`:

```python
from src.intake_extract import SearchTerms, extract_search_terms


def test_picks_up_a_role_title_from_the_text():
    terms = extract_search_terms("I'm a backend engineer these days")
    assert "backend engineer" in terms.keywords
    assert terms.guessed is False


def test_picks_up_role_titles_from_the_resume():
    terms = extract_search_terms("", resume_text="Senior Data Scientist, Acme")
    assert any("data scientist" in k for k in terms.keywords)


def test_includes_vocabulary_terms():
    terms = extract_search_terms(
        "backend engineer working in python", vocabulary={"python"}
    )
    assert "python" in terms.keywords


def test_falls_back_to_defaults_and_says_so():
    terms = extract_search_terms("")
    assert terms.guessed is True
    assert terms.keywords


def test_keywords_are_capped_and_unique():
    terms = extract_search_terms(
        "python python typescript rust go java scala kotlin",
        vocabulary={"python", "typescript", "rust", "go", "java", "scala", "kotlin"},
        limit=4,
    )
    assert len(terms.keywords) == 4
    assert len(set(terms.keywords)) == 4


def test_is_hashable_so_it_can_be_cached():
    assert isinstance(extract_search_terms("backend engineer"), SearchTerms)
    hash(extract_search_terms("backend engineer"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_intake_extract.py -v`
Expected: FAIL with `ImportError: cannot import name 'SearchTerms' from 'src.intake_extract'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/intake_extract.py`:

```python
_ROLE_WORDS = (
    "engineer", "developer", "scientist", "analyst", "designer", "manager",
    "researcher", "architect", "administrator", "consultant",
)

# Up to two qualifying words before the role noun: "senior data scientist",
# "backend engineer", "engineer".
#
# Qualifiers need two or more characters (``+`` not ``*``). With ``*``, the "m"
# left over from "I'm" is a valid qualifier and "I'm a backend engineer" yields
# "m backend engineer".
_ROLE_TITLE = re.compile(
    r"\b((?:[A-Za-z][\w+#.-]+\s+){0,2}(?:" + "|".join(_ROLE_WORDS) + r"))\b",
    re.IGNORECASE,
)

# Qualifiers that are grammatical filler rather than part of a job title.
_TITLE_NOISE = frozenset({"a", "an", "the", "am", "im", "i'm", "as", "was", "is", "and", "or"})

_DEFAULT_KEYWORDS = ("software engineer", "backend engineer")


@dataclass(frozen=True)
class SearchTerms:
    """What we would go looking for, offered to the user for correction.

    ``guessed`` is True when nothing could be derived and defaults were used, so
    the UI can hedge rather than present a guess as a finding.
    """

    keywords: tuple[str, ...]
    guessed: bool


def _clean_title(raw: str) -> str:
    words = [w for w in raw.split() if w.lower() not in _TITLE_NOISE]
    return " ".join(words).lower().strip()


def extract_search_terms(
    text: str,
    resume_text: str = "",
    *,
    vocabulary: set[str] | None = None,
    limit: int = 6,
) -> SearchTerms:
    """Derive job-search keywords from what the user already told us.

    The user never fills in a search form: we propose from their own words and
    they correct us.
    """
    haystack = f"{text}\n{resume_text}"
    low = haystack.lower()
    keywords: list[str] = []

    for match in _ROLE_TITLE.finditer(haystack):
        title = _clean_title(match.group(1))
        if title and title not in keywords:
            keywords.append(title)

    for term in sorted(vocabulary or set()):
        if term in _STOPLIST:
            continue
        if re.search(rf"\b{re.escape(term)}\b", low) and term not in keywords:
            keywords.append(term)

    if not keywords:
        return SearchTerms(keywords=_DEFAULT_KEYWORDS, guessed=True)
    return SearchTerms(keywords=tuple(keywords[:limit]), guessed=False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_intake_extract.py -v`
Expected: 20 passed

- [ ] **Step 5: Commit**

```bash
git add src/intake_extract.py tests/test_intake_extract.py
git commit -m "feat: derive job-search keywords from the user's own words"
```

---

### Task 5: Intake storage

**Files:**
- Create: `server/intake.py`
- Test: `tests/test_intake_storage.py`

**Interfaces:**
- Consumes: `UserPaths` intake properties from Task 1.
- Produces:
  - `save_notes(paths: UserPaths, text: str) -> Path`
  - `park_resume(paths: UserPaths, text: str) -> Path`
  - `save_draft_story(paths: UserPaths, title: str, body: str) -> Path`
  - `list_drafts(paths: UserPaths) -> list[dict]` — each `{"slug": str, "title": str, "captured_at": str, "body": str}`
  - `read_notes(paths: UserPaths) -> str`, `read_parked_resume(paths: UserPaths) -> str` — `""` when absent
  - `slugify(text: str) -> str`

- [ ] **Step 1: Write the failing test**

Create `tests/test_intake_storage.py`:

```python
"""Writing raw captured material to the _intake tree.

Slugs come from user-supplied titles, so containment is a security property
here, not a tidiness one.
"""
from __future__ import annotations

import pytest

from server.intake import (
    list_drafts,
    park_resume,
    read_notes,
    read_parked_resume,
    save_draft_story,
    save_notes,
    slugify,
)
from server.user_paths import PathEscape, UserPaths, resolve_within


@pytest.fixture()
def paths():
    return UserPaths(user_id=1).ensure()


def test_notes_round_trip(paths):
    save_notes(paths, "I mostly do backend work.")
    assert read_notes(paths) == "I mostly do backend work."


def test_reading_absent_notes_returns_empty_string(paths):
    assert read_notes(paths) == ""


def test_parked_resume_round_trip(paths):
    park_resume(paths, "Jane Doe\nSenior Engineer")
    assert "Senior Engineer" in read_parked_resume(paths)


def test_draft_story_is_written_with_frontmatter(paths):
    path = save_draft_story(paths, "The payments migration", "It was messy.")
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "draft: true" in text
    assert "It was messy." in text


def test_draft_story_keeps_the_body_verbatim(paths):
    body = "we shipped it   on a Friday\n\nwhich was a mistake"
    path = save_draft_story(paths, "Friday", body)
    assert body in path.read_text(encoding="utf-8")


def test_draft_lands_outside_the_real_stories_dir(paths):
    save_draft_story(paths, "A draft", "body")
    real = [p for p in paths.stories_dir.glob("*.md") if not p.name.startswith("_")]
    assert real == []


def test_colliding_titles_do_not_overwrite(paths):
    first = save_draft_story(paths, "Same title", "first body")
    second = save_draft_story(paths, "Same title", "second body")
    assert first != second
    assert "first body" in first.read_text(encoding="utf-8")
    assert "second body" in second.read_text(encoding="utf-8")


def test_list_drafts_returns_what_was_saved(paths):
    save_draft_story(paths, "One", "first")
    save_draft_story(paths, "Two", "second")
    drafts = list_drafts(paths)
    assert {d["title"] for d in drafts} == {"One", "Two"}
    assert all(d["captured_at"] for d in drafts)


def test_list_drafts_on_empty_tree(paths):
    assert list_drafts(paths) == []


def test_slugify_neutralises_traversal_input():
    assert "/" not in slugify("../../etc/passwd")
    assert ".." not in slugify("../../etc/passwd")


def test_slugify_falls_back_when_nothing_survives():
    assert slugify("!!!") == "story"


def test_a_crafted_slug_cannot_escape_the_intake_dir(paths):
    with pytest.raises(PathEscape):
        resolve_within(paths.intake_stories_dir, "../../../evil.md")


def test_traversal_title_still_lands_inside_intake(paths):
    path = save_draft_story(paths, "../../etc/passwd", "body")
    assert path.is_relative_to(paths.intake_stories_dir)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_intake_storage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'server.intake'`

- [ ] **Step 3: Write minimal implementation**

Create `server/intake.py`:

```python
"""Read and write the per-user ``_intake`` tree.

The onboarding journey captures raw human material before the user has an API
key, so nothing here calls a provider. Enrichment (plan 2) turns this material
into ``resume.yaml``, tagged stories and ``bio.md`` once a key exists.

This module is the only place that knows the intake layout; everything else
goes through these functions.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from .user_paths import UserPaths, resolve_within

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_FRONTMATTER = re.compile(r"^---\n(?P<meta>.*?)\n---\n(?P<body>.*)$", re.S)


def slugify(text: str) -> str:
    """A filesystem-safe slug. Never empty, never contains a path separator.

    Titles are user-supplied, so this is the first of two defences: the slug
    cannot express traversal, and ``resolve_within`` then proves containment
    anyway. Either alone would be enough; both is cheap.
    """
    slug = _SLUG_STRIP.sub("-", text.lower()).strip("-")[:60].strip("-")
    return slug or "story"


def save_notes(paths: UserPaths, text: str) -> Path:
    paths.ensure()
    paths.intake_notes_path.write_text(text, encoding="utf-8")
    return paths.intake_notes_path


def read_notes(paths: UserPaths) -> str:
    if not paths.intake_notes_path.exists():
        return ""
    return paths.intake_notes_path.read_text(encoding="utf-8")


def park_resume(paths: UserPaths, text: str) -> Path:
    """Store extracted resume *text* as-is.

    Deliberately not parsed into ``resume.yaml``: that needs an LLM, and the
    journey runs before there is a key. Parking means capture cannot fail
    because a model was down, a key was wrong, or a quota was hit.
    """
    paths.ensure()
    paths.intake_resume_path.write_text(text, encoding="utf-8")
    return paths.intake_resume_path


def read_parked_resume(paths: UserPaths) -> str:
    if not paths.intake_resume_path.exists():
        return ""
    return paths.intake_resume_path.read_text(encoding="utf-8")


def _unique_path(directory: Path, slug: str) -> Path:
    candidate = resolve_within(directory, f"{slug}.md")
    counter = 2
    while candidate.exists():
        candidate = resolve_within(directory, f"{slug}-{counter}.md")
        counter += 1
    return candidate


def save_draft_story(paths: UserPaths, title: str, body: str) -> Path:
    """Save one told story verbatim, as a draft.

    The body is written untouched. It is the user's own words, and enrichment
    later works from them — editing here would mean the model shapes what it is
    later asked to shape.
    """
    paths.ensure()
    path = _unique_path(paths.intake_stories_dir, slugify(title))
    captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    safe_title = title.replace('"', "'")
    path.write_text(
        f'---\ndraft: true\ntitle: "{safe_title}"\ncaptured_at: "{captured_at}"\n---\n\n{body}',
        encoding="utf-8",
    )
    return path


def _parse_draft(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(text)
    meta, body = ({}, text)
    if match:
        body = match.group("body")
        for line in match.group("meta").splitlines():
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip().strip('"')
    return {
        "slug": path.stem,
        "title": meta.get("title", path.stem),
        "captured_at": meta.get("captured_at", ""),
        "body": body,
    }


def list_drafts(paths: UserPaths) -> list[dict]:
    if not paths.intake_stories_dir.exists():
        return []
    return [_parse_draft(p) for p in sorted(paths.intake_stories_dir.glob("*.md"))]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_intake_storage.py -v`
Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
git add server/intake.py tests/test_intake_storage.py
git commit -m "feat: store raw onboarding material in the _intake tree"
```

---

### Task 6: Intake endpoints

**Files:**
- Modify: `server/onboarding.py` — add imports, five routes, and the `intake` block in `_compute_status` (`server/onboarding.py:96-131`)
- Test: `tests/test_intake_api.py`

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces:
  - `POST /api/onboarding/intake/notes` — body `{"text": str}` → `{"ok": true}`
  - `POST /api/onboarding/intake/resume` — multipart `file` → `{"ok": true, "chars": int}`
  - `POST /api/onboarding/intake/story` — body `{"title": str, "body": str}` → `{"ok": true, "slug": str}`
  - `GET /api/onboarding/intake/threads` → `{"threads": [{"label": str, "kind": str}]}`
  - `GET /api/onboarding/intake/search-terms` → `{"keywords": [str], "guessed": bool}`
  - `GET /api/onboarding/status` gains `intake: {"notes": bool, "resume_text": bool, "drafts": int}`

- [ ] **Step 1: Write the failing test**

Create `tests/test_intake_api.py`:

```python
"""Intake endpoints.

The load-bearing assertion in this file is that every one of these works with
no API key configured. Capture happens before the user has a provider; if any
of this needs one, the journey is broken at its first chapter.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server.db as db

from .conftest import make_engine, register


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, "engine", engine)
    from server.app import app

    return app


@pytest.fixture()
def client(app_env):
    with TestClient(app_env) as c:
        register(c, "a@example.com")
        yield c


def test_notes_are_saved_without_any_provider_configured(client):
    r = client.post(
        "/api/onboarding/intake/notes",
        json={"text": "I built the payments migration at Stripe."},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_resume_upload_parks_text_without_any_provider_configured(client):
    r = client.post(
        "/api/onboarding/intake/resume",
        files={"file": ("cv.txt", b"Jane Doe\nSenior Backend Engineer", "text/plain")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["chars"] > 0


def test_threads_come_back_from_the_saved_notes(client):
    client.post(
        "/api/onboarding/intake/notes",
        json={"text": "I built the payments migration at Stripe, mostly python."},
    )
    r = client.get("/api/onboarding/intake/threads")
    assert r.status_code == 200, r.text
    labels = {t["label"].lower() for t in r.json()["threads"]}
    assert "stripe" in labels
    assert "python" in labels


def test_threads_on_an_empty_account_are_empty_not_an_error(client):
    r = client.get("/api/onboarding/intake/threads")
    assert r.status_code == 200
    assert r.json()["threads"] == []


def test_search_terms_are_derived_and_flagged_when_guessed(client):
    r = client.get("/api/onboarding/intake/search-terms")
    assert r.status_code == 200
    assert r.json()["guessed"] is True

    client.post(
        "/api/onboarding/intake/notes",
        json={"text": "I'm a backend engineer who writes python"},
    )
    r = client.get("/api/onboarding/intake/search-terms")
    body = r.json()
    assert body["guessed"] is False
    assert "backend engineer" in body["keywords"]


def test_draft_story_is_saved_and_does_not_count_as_a_real_story(client):
    r = client.post(
        "/api/onboarding/intake/story",
        json={"title": "The payments migration", "body": "It was messy."},
    )
    assert r.status_code == 200, r.text
    assert r.json()["slug"] == "the-payments-migration"

    status = client.get("/api/onboarding/status").json()
    assert status["steps"]["stories"] == 0
    assert status["intake"]["drafts"] == 1


def test_status_reports_the_intake_block(client):
    status = client.get("/api/onboarding/status").json()
    assert status["intake"] == {"notes": False, "resume_text": False, "drafts": 0}

    client.post("/api/onboarding/intake/notes", json={"text": "hello"})
    status = client.get("/api/onboarding/status").json()
    assert status["intake"]["notes"] is True


def test_intake_requires_a_session(app_env):
    with TestClient(app_env) as anon:
        assert anon.get("/api/onboarding/intake/threads").status_code == 401


def test_one_users_intake_is_invisible_to_another(app_env):
    with TestClient(app_env) as ca, TestClient(app_env) as cb:
        register(ca, "a@example.com")
        register(cb, "b@example.com")
        ca.post("/api/onboarding/intake/notes", json={"text": "worked at Figma"})
        threads = cb.get("/api/onboarding/intake/threads").json()["threads"]
        assert threads == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_intake_api.py -v`
Expected: FAIL — 404s on every intake route, and `KeyError: 'intake'` on the status tests.

- [ ] **Step 3: Write minimal implementation**

In `server/onboarding.py`, add to the imports at the top:

```python
from functools import lru_cache

from . import intake as intake_store
from .user_paths import GLOBAL_MASTER_DIR
from src.intake_extract import extract_search_terms, extract_threads, load_vocabulary
from src.scrapers.greenhouse_companies import BUILT_IN_SLUGS
```

Then add, after the existing `_count_stories` helper:

```python
@lru_cache(maxsize=1)
def _vocabulary() -> frozenset[str]:
    """The committed tag taxonomy, parsed once.

    Safe to cache, unlike per-user paths: this file is global, committed and
    identical for every account.
    """
    index = GLOBAL_MASTER_DIR / "stories" / "_INDEX.md"
    if not index.exists():
        return frozenset()
    return frozenset(load_vocabulary(index.read_text(encoding="utf-8")))


def _intake_corpus(paths) -> tuple[str, str]:
    """Everything the user has told us so far: (typed text, resume text)."""
    told = intake_store.read_notes(paths)
    drafts = intake_store.list_drafts(paths)
    if drafts:
        told = "\n\n".join([told, *(d["body"] for d in drafts)]).strip()
    return told, intake_store.read_parked_resume(paths)
```

Add the `intake` block to `_compute_status`, just before the `return`:

```python
    drafts = intake_store.list_drafts(paths)
```

and inside the returned dict:

```python
        "intake": {
            "notes": bool(intake_store.read_notes(paths).strip()),
            "resume_text": bool(intake_store.read_parked_resume(paths).strip()),
            "drafts": len(drafts),
        },
```

Then add the routes at the end of the file:

```python
# --- Intake: raw capture, no LLM ---------------------------------------------
#
# Every endpoint below must work with no provider configured. The journey
# collects material before asking for an API key, so a provider call here would
# break the first chapter for exactly the users it exists to serve.


class NotesBody(BaseModel):
    text: str


@router.post("/intake/notes")
def save_intake_notes(
    body: NotesBody, user: User = Depends(require_user)
) -> dict:
    intake_store.save_notes(paths_for(user), body.text)
    return {"ok": True}


@router.post("/intake/resume")
async def park_intake_resume(
    file: UploadFile | None = File(default=None),
    user: User = Depends(require_user),
) -> dict:
    """Extract text from an uploaded resume and park it — no LLM.

    ``resume-import`` above does the structured extraction and needs a key; this
    one deliberately does not, so the resume is never a wall.
    """
    if file is None:
        raise HTTPException(400, "no file uploaded")
    data = await file.read()
    text = _extract_text(file.filename or "resume", data)
    if not text.strip():
        raise HTTPException(400, "could not read any text from that file")
    intake_store.park_resume(paths_for(user), text)
    return {"ok": True, "chars": len(text)}


class DraftStoryBody(BaseModel):
    title: str
    body: str


@router.post("/intake/story")
def save_intake_story(
    body: DraftStoryBody, user: User = Depends(require_user)
) -> dict:
    if not body.body.strip():
        raise HTTPException(400, "story body is empty")
    path = intake_store.save_draft_story(paths_for(user), body.title, body.body)
    return {"ok": True, "slug": path.stem}


@router.get("/intake/threads")
def intake_threads(user: User = Depends(require_user)) -> dict:
    told, resume_text = _intake_corpus(paths_for(user))
    threads = extract_threads(
        told,
        resume_text,
        vocabulary=set(_vocabulary()),
        companies=BUILT_IN_SLUGS,
    )
    return {"threads": [{"label": t.label, "kind": t.kind} for t in threads]}


@router.get("/intake/search-terms")
def intake_search_terms(user: User = Depends(require_user)) -> dict:
    told, resume_text = _intake_corpus(paths_for(user))
    terms = extract_search_terms(told, resume_text, vocabulary=set(_vocabulary()))
    return {"keywords": list(terms.keywords), "guessed": terms.guessed}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_intake_api.py -v`
Expected: 9 passed

- [ ] **Step 5: Run the whole suite, including the scope lint**

Run: `python -m pytest tests/ -q`
Expected: all pass. `tests/test_scope_lint.py` in particular must stay green — this task adds no DB queries, so any failure there means something unintended was introduced.

- [ ] **Step 6: Commit**

```bash
git add server/onboarding.py tests/test_intake_api.py
git commit -m "feat: intake endpoints for key-free onboarding capture"
```

---

## Self-Review

**Spec coverage for this plan's scope:**

| Spec requirement | Task |
|---|---|
| `_intake/` layout owned by `UserPaths` | 1 |
| Drafts invisible to `stories/` glob | 1, 5, 6 |
| `consumed/` exists so drafts are moved not deleted | 1 (directory); plan 2 uses it |
| `src/intake_extract.py`, pure and LLM-free | 2, 3, 4 |
| Vocabulary from `_INDEX.md` taxonomy | 2 |
| Company names from `greenhouse_companies.py` | 3, 6 |
| Verb-anchored phrases | 3 |
| Stoplist, cap of 8, precision bias | 3 |
| `guessed` hedging on search terms | 4 |
| Resume text parked, not parsed | 5, 6 |
| Draft stories saved verbatim | 5 |
| Path containment for user-supplied slugs | 5 |
| `/status` gains an `intake` block | 6 |
| Nothing requires a provider | 6 (explicitly asserted) |

**Deferred to plan 2** (in the spec, not in this plan): `POST /preview-jobs`, `enrich/plan`, `enrich/step`, `server/profile_strength.py`, `server/provider_setup.py`.
**Deferred to plan 3:** all frontend work, sample-fill, the fingerprint component.

**Known imprecision, accepted deliberately:** `_VERB_ANCHOR` caps phrases at two words, so "built the new payments reconciliation service" yields "new payments". Consistent with precision-over-recall — the chip is still recognisable and the user can pick "something else". Widening it lets trailing sentence fragments in, which is the worse failure.

## Manual verification after Task 6

```bash
python -m pytest tests/ -q
python -c "from pathlib import Path; from src.intake_extract import load_vocabulary, extract_threads; from src.scrapers.greenhouse_companies import BUILT_IN_SLUGS; v = load_vocabulary(Path('master_data/stories/_INDEX.md').read_text(encoding='utf-8')); print(extract_threads('I built the payments migration at Stripe, mostly python and postgres', vocabulary=v, companies=BUILT_IN_SLUGS))"
```

Expected: a short list led by `Thread(label='Stripe', kind='company')`, followed by topic chips for the tags that are actually in the taxonomy, and the phrase `payments migration`. Eyeball it — the whole point of this plan is that a human would recognise these as "things I just said".
