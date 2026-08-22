# Demo Account Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a shared, committable "John Doe" demo account that anyone can enter from the login page, in which every flow — including the AI ones — works end to end against simulated model responses.

**Architecture:** A committed `demo_data/` fixture tree is seeded by `server/demo.py` into the demo user's ordinary `data/users/<id>/` tree and Postgres rows. The demo account's `config.yaml` sets `llm.primary: demo`, which routes every LLM call to a new `DemoProvider` returning canned, schema-valid responses — so no module in `src/` other than the provider factory learns that a demo exists. A public, per-IP rate-limited `POST /api/auth/demo` mints an ordinary session.

**Tech Stack:** Python 3.11 / FastAPI / SQLModel / Alembic / pytest on the server; Next.js 16 App Router / TanStack Query / shadcn-ui on the web.

**Spec:** `docs/superpowers/specs/2026-08-21-demo-account-design.md`

**Issue:** [#38](https://github.com/sanaro99/applination/issues/38)

## Global Constraints

- **This repository is public.** Every value committed under `demo_data/` must be fictional. The persona's own employers and schools are invented; real company names appear only as public job postings. Contact values are reserved examples (`demo@applination.app`, `+1-555-0100`).
- **No new DB column and no Alembic migration.** The demo account is identified by the constant `DEMO_EMAIL = "demo@applination.app"`, overridable by the `DEMO_EMAIL` env var.
- **`src/` must never import `server/`.** `DemoProvider` locates its fixtures from the repo root or from config, never through `server.user_paths`.
- **Every DB query in `server/demo.py` needs `# noscope: <reason>`** or `tests/test_scope_lint.py` fails the build. The reason is that the seeder runs outside any request against a known, constant user id.
- **Never commit anything under `/data/users/`** — it is gitignored and holds the demo's *live* tree, which is seeded, not committed.
- Conventional-commit prefixes: `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`.
- Run the suite with `python -m pytest`. Tests use SQLite; production is Postgres.

---

### Task 1: `DemoProvider` — simulated LLM responses

**Files:**
- Create: `src/providers/demo_provider.py`
- Modify: `src/providers/factory.py:65-142` (add a `demo` branch to `get_provider`, and the unknown-provider error message)
- Create: `demo_data/llm/README.md`, `demo_data/llm/cover_letter.txt`, `demo_data/llm/coach.txt`, `demo_data/llm/interview_kickoff.txt`, `demo_data/llm/interview_turn.txt`, `demo_data/llm/essay.txt`, `demo_data/llm/generic.txt`
- Test: `tests/test_demo_provider.py`

**Interfaces:**
- Consumes: `LLMProvider` ABC from `src/providers/base.py` — `text_call(self, system, user, max_tokens=1000) -> str` and `json_call(self, system, user, max_tokens=2000, *, schema=None) -> dict`. Note `json_call` receives **no task name**; dispatch must use `schema` alone.
- Produces: `DemoProvider(fixtures_dir: Path | None = None, delay: tuple[float, float] = (0.4, 1.2))` with `name = "demo"`. Task 2 relies on `get_provider("demo", cfg["llm"])` working. Task 5 relies on `DemoProvider` being reachable via `llm.primary: demo`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_demo_provider.py`:

```python
"""The demo provider must be indistinguishable from a real one to callers.

Every flow in the app funnels through text_call/json_call. If the demo
provider can return something schema-invalid, the demo breaks in exactly the
places a visitor is most likely to click.
"""
from __future__ import annotations

import pytest

from src.providers.demo_provider import DemoProvider
from src.providers.factory import get_provider
from src.schemas.resume_schema import RESUME_SCHEMA
from src.schemas.story_schema import STORY_SCHEMA
from src.schemas.master_resume_schema import MASTER_RESUME_SCHEMA
from src.schemas.keywords_schema import KEYWORDS_SCHEMA


@pytest.fixture
def provider() -> DemoProvider:
    # No delay under test: the sleep exists for demo realism, and paying it in
    # the suite would add minutes for no assertion.
    return DemoProvider(delay=(0.0, 0.0))


def test_factory_builds_it_by_name():
    p = get_provider("demo", {"demo": {}})
    assert p.name == "demo"


def test_cover_letter_prompt_returns_prose(provider):
    out = provider.text_call(
        "ABSOLUTE OUTPUT RULES ... 3-paragraph cover letter body ...", "job"
    )
    assert len(out.split()) > 40
    # The renderer adds the sign-off; a letter body carrying its own would
    # render two.
    assert "Sincerely" not in out


def test_coach_prompt_differs_from_cover_letter(provider):
    letter = provider.text_call("... 3-paragraph cover letter body ...", "u")
    coach = provider.text_call("You are Coach, a career assistant for John.", "u")
    assert letter != coach


def test_interview_turn_has_the_three_labels(provider):
    out = provider.text_call(
        "You are Coach, running a mock interview with John. "
        "Feedback: 2-3 sentences", "u",
    )
    for label in ("Feedback", "Model answer", "Next question"):
        assert label in out


def test_unknown_text_prompt_still_returns_something(provider):
    out = provider.text_call("some prompt nobody planned for", "u")
    assert out.strip()


@pytest.mark.parametrize(
    "schema",
    [RESUME_SCHEMA, STORY_SCHEMA, MASTER_RESUME_SCHEMA, KEYWORDS_SCHEMA],
)
def test_known_schemas_validate(provider, schema):
    jsonschema = pytest.importorskip("jsonschema")
    out = provider.json_call("sys", "user", schema=schema)
    jsonschema.validate(out, schema)


def test_ranking_call_has_no_schema_but_needs_scores(provider):
    # tailor.rank_jobs calls json_call WITHOUT a schema and parses resp["scores"].
    out = provider.json_call(
        'Return a JSON object with key "scores" containing an array', "u"
    )
    assert isinstance(out.get("scores"), list)
    assert {"idx", "score", "reason"} <= set(out["scores"][0])


def test_unknown_schema_is_synthesised_and_valid(provider):
    jsonschema = pytest.importorskip("jsonschema")
    schema = {
        "type": "object",
        "properties": {
            "verdict": {"type": "string"},
            "confidence": {"type": "number"},
            "flags": {"type": "array", "items": {"type": "string"}},
            "ok": {"type": "boolean"},
        },
        "required": ["verdict", "confidence", "flags", "ok"],
        "additionalProperties": False,
    }
    out = provider.json_call("sys", "user", schema=schema)
    jsonschema.validate(out, schema)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_demo_provider.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.providers.demo_provider'`.

- [ ] **Step 3: Add `jsonschema` to the test requirements if it is absent**

Run: `python -c "import jsonschema; print(jsonschema.__version__)"`
If it raises `ModuleNotFoundError`, append `jsonschema>=4.21` to `requirements.txt` and run `pip install jsonschema`. The `importorskip` in the tests keeps them honest either way, but the assertions are the point — install it.

- [ ] **Step 4: Write the text fixtures**

Create `demo_data/llm/README.md`:

```markdown
# Canned responses for the demo account

`src/providers/demo_provider.py` serves these instead of calling a model, so
the demo account can exercise every AI flow without an API key and without
spending anyone's money.

Each `.txt` file is one response, chosen by matching cues in the system
prompt. `generic.txt` is the fallback. Keep them in John Doe's voice and
consistent with `demo_data/master_data/` — a visitor who reads the resume and
then the cover letter should see the same person.
```

Create `demo_data/llm/cover_letter.txt` (three paragraphs, no sign-off, no em dashes — `src/tailor.py` strips them for ATS safety and a fixture containing them is a silent inconsistency):

```
I read the posting twice, mostly because of the line about owning a service end to end rather than shipping a feature and moving on. That is the part of the job I have been chasing. At Northwind Analytics I inherited a batch pipeline that quietly dropped about 4% of events, and the fix was not clever code; it was two weeks of reading the retry logic until the failure mode was obvious. Throughput went up 30% once it stopped silently retrying itself into a corner.

Most of what I would bring is that habit. I built an internal dashboard at Trellis Labs that cut on-call triage time roughly in half, and the reason it worked was not the charts. It was sitting with the two engineers who got paged most and finding out that they always checked the same three things in the same order. I am comfortable being the person who asks the boring questions early so the interesting work is not built on a guess.

I am finishing my degree this spring and looking for a team that treats production as part of the craft rather than someone else's problem. The work described here reads like that, and I would like to talk about it.
```

Create `demo_data/llm/coach.txt`:

```
Good question to prepare for, and you have stronger material for it than you are using.

**Lead with the pipeline story.** The Northwind event-loss work is your best answer to anything about debugging, ownership, or persistence. The shape that works: the pipeline was dropping about 4% of events, nobody had noticed because the retry logic made the failure look like normal load, and it took two weeks of reading code to find. Land on the number — 30% throughput improvement — because it makes the whole story concrete.

**What to tighten.** You tend to open with context and take too long to reach what you actually did. Try starting with the problem in one sentence, then go straight to your decision. The background can come out in follow-up questions.

**One thing to add.** Say what you would do differently. For this story that is easy and honest: you would have added the alerting first, because the reason it went unnoticed for months was that nothing was watching. Interviewers read that as judgment rather than as a weakness.
```

Create `demo_data/llm/interview_kickoff.txt`:

```
Thanks for making the time. I would like to spend most of this on how you work through problems rather than on your resume, so I will start broad.

Tell me about a time you found a bug that had been present for a while without anyone noticing. What made it hard to see, and how did you eventually track it down?
```

Create `demo_data/llm/interview_turn.txt`:

```
**Feedback:** The story is a good choice and the 4% figure gives it weight, but you spent most of the answer on the architecture before getting to what you personally did. Interviewers are listening for your decisions. Also, you said the fix "just worked" — say what you actually changed and why you believed it would help.

**Model answer:** "A batch pipeline I owned at Northwind was dropping about 4% of events. It was invisible because the retry logic swallowed the failures and the graphs looked like normal load. I spent two weeks reading the retry path rather than adding instrumentation first, which in hindsight was backwards. The bug was that a retry re-enqueued to the same partition that was already saturated, so a slow consumer became a lossy one. I changed the retry to a separate queue with a backoff, and throughput went up about 30%. The lasting fix was the alert I added afterward, because the real failure was that nothing had been watching."

**Next question:** Tell me about a time you disagreed with a technical decision someone more senior had made. What did you do?
```

Create `demo_data/llm/essay.txt`:

```
The work I am proudest of did not look impressive while I was doing it. A batch pipeline I owned at Northwind Analytics was losing about 4% of its events, and it had been doing so for months without anyone noticing, because the retry logic turned every dropped event into something that looked like ordinary load. I spent two weeks reading that retry path line by line. There was no insight to have; there was only the code, and eventually the moment where I understood that a retry re-enqueued to the partition that was already saturated, so a slow consumer became a lossy one.

Fixing it took an afternoon and raised throughput by about 30%. What I took from it was not the fix but the alert I added afterward. The bug had survived because nothing was watching, and I have since found that most of the failures worth preventing are like that: not hard to solve, just easy to miss. I try to be the person who asks what would tell us if this broke, and to ask it while the answer is still cheap.
```

Create `demo_data/llm/generic.txt`:

```
Here is a draft based on what is in John Doe's profile. It leans on the Northwind pipeline work and the Trellis Labs dashboard, since those are the two pieces of experience with concrete numbers attached, and keeps the tone plain and specific rather than promotional.
```

- [ ] **Step 5: Write the provider**

Create `src/providers/demo_provider.py`:

```python
"""A provider that fakes it, on purpose.

The demo account has no API key and never will: it is shared, public, and
anyone can walk into it from the login page. But an AI product whose AI errors
demonstrates nothing, so instead of blocking the LLM calls we answer them from
committed fixtures.

Doing it at the provider layer is what keeps this cheap. The demo account's
config sets ``llm.primary: demo``, and from there the ranker, the tailoring
graph, the cover-letter writer, Coach, the mock interview, the essay drafter
and content studio all run their real code paths unmodified. Nothing else in
``src/`` or ``server/`` knows the demo exists.

Two dispatch problems, because the two entry points carry different
information:

* ``text_call`` gets a system prompt, so it can be matched on cues from the
  real prompts (``tailor.write_cover_letter``, ``coach_context``).
* ``json_call`` gets a ``schema`` and *no task name* — that is the actual
  signature in ``base.py``. So it fingerprints the schema's required keys, and
  anything unrecognised is synthesised from the schema itself. A task added
  later degrades to generic-but-valid output instead of breaking the demo.
"""
from __future__ import annotations

import json
import logging
import random
import time
from pathlib import Path

from .base import LLMProvider

LOG = logging.getLogger(__name__)

# demo_data/ sits at the repository root, beside src/ and server/. It is a
# committed asset like master_data/guidelines, not per-user data.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_FIXTURES = _REPO_ROOT / "demo_data" / "llm"

# Ordered: the first match wins, so the more specific cue must come first.
# "an interviewer running a mock interview" (kickoff) would otherwise be
# swallowed by "running a mock interview" (the per-turn prompt).
_TEXT_CUES: tuple[tuple[str, str], ...] = (
    ("cover letter body", "cover_letter.txt"),
    ("an interviewer running a mock interview", "interview_kickoff.txt"),
    ("running a mock interview", "interview_turn.txt"),
    ("drafting an application answer", "essay.txt"),
    ("you are coach", "coach.txt"),
)


class DemoProvider(LLMProvider):
    name = "demo"

    def __init__(
        self,
        fixtures_dir: Path | str | None = None,
        delay: tuple[float, float] = (0.4, 1.2),
    ) -> None:
        self.fixtures_dir = Path(fixtures_dir) if fixtures_dir else _DEFAULT_FIXTURES
        self.delay = delay
        self._rng = random.Random()

    # -- plumbing ---------------------------------------------------------
    def _sleep(self) -> None:
        """Pause the way a real call would.

        Without this the run page's SSE stream completes instantly and Coach
        answers before the typing indicator paints, which reads as canned even
        though the content is fine. Realism cuts both ways.
        """
        low, high = self.delay
        if high > 0:
            time.sleep(self._rng.uniform(low, high))

    def _fixture(self, filename: str) -> str:
        path = self.fixtures_dir / filename
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            LOG.warning("demo fixture missing: %s", path)
            return ""

    # -- LLMProvider ------------------------------------------------------
    def text_call(self, system: str, user: str, max_tokens: int = 1000) -> str:
        self._sleep()
        haystack = (system or "").lower()
        for cue, filename in _TEXT_CUES:
            if cue in haystack:
                text = self._fixture(filename)
                if text:
                    return self._post_process_text(text)
        return self._post_process_text(self._fixture("generic.txt"))

    def json_call(
        self,
        system: str,
        user: str,
        max_tokens: int = 2000,
        *,
        schema: dict | None = None,
    ) -> dict:
        self._sleep()
        if schema is None:
            # The ranker is the one caller that passes no schema; it asks for
            # {"scores": [{"idx", "score", "reason"}]} in prose and parses that
            # key directly (src/tailor.py rank_jobs -> _parse_scores).
            if "scores" in (system or ""):
                return self._ranking_response(user)
            return {}
        return _synthesise(schema, rng=self._rng)

    def _ranking_response(self, user: str) -> dict:
        """Score every ``[idx]`` the batch prompt listed.

        The count has to match the batch: ``_parse_scores`` is given
        ``batch_size`` and a short list silently drops jobs from the run.
        """
        import re

        indices = [int(m) for m in re.findall(r"^\s*\[(\d+)\]", user or "", re.M)]
        if not indices:
            indices = list(range(15))
        scores = []
        for i in indices:
            # Deterministic per index so two runs of the demo are comparable in
            # the run-diff view, and spread across the threshold so the triage
            # tab has both selected and rejected jobs to show.
            value = 45 + (i * 37) % 50
            scores.append({
                "idx": i,
                "score": value,
                "reason": (
                    "Strong overlap with the data-pipeline and reliability work."
                    if value >= 70
                    else "Partial match; the role leans on skills not evidenced."
                ),
            })
        return {"scores": scores}


def _synthesise(schema: dict, *, rng: random.Random, depth: int = 0):
    """Build a value that satisfies ``schema``.

    Deliberately schema-driven rather than a fixture lookup. Fixtures would
    have to be revised every time a prompt's schema changed, and a stale
    fixture fails as a JSON-parse error deep inside the tailoring graph —
    which is a miserable thing to debug in a demo. Walking the schema cannot
    go stale.

    Strings are keyed off the property name so the output reads like a resume
    rather than like "string": a ``company`` gets a company, ``bullets`` get
    bullets of a plausible length.
    """
    if depth > 12:  # pathological/recursive schema guard
        return {}
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), "string")

    if "enum" in schema:
        return schema["enum"][0]

    if kind == "object" or "properties" in schema:
        props: dict = schema.get("properties") or {}
        required = schema.get("required") or list(props)
        out = {}
        for key in required:
            sub = props.get(key, {"type": "string"})
            out[key] = _synthesise_named(key, sub, rng=rng, depth=depth + 1)
        return out

    if kind == "array":
        item_schema = schema.get("items") or {"type": "string"}
        count = max(int(schema.get("minItems", 0)), 3)
        count = min(count, int(schema.get("maxItems", count)))
        return [
            _synthesise(item_schema, rng=rng, depth=depth + 1) for _ in range(count)
        ]

    if kind == "integer":
        return int(schema.get("minimum", 0)) or 3
    if kind == "number":
        return float(schema.get("minimum", 0)) or 0.85
    if kind == "boolean":
        return True
    return _string_for("", schema)


def _synthesise_named(key: str, schema: dict, *, rng: random.Random, depth: int):
    kind = schema.get("type")
    if kind == "string" or (kind is None and "properties" not in schema
                            and "items" not in schema and "enum" not in schema):
        return _string_for(key, schema)
    if kind == "array" and (schema.get("items") or {}).get("type") == "string":
        item = schema.get("items") or {}
        count = max(int(schema.get("minItems", 0)), 3)
        count = min(count, int(schema.get("maxItems", count)))
        return [_string_for(key, item) for _ in range(count)]
    return _synthesise(schema, rng=rng, depth=depth)


# Property-name hints. Anything unmatched falls back to filler text padded to
# the schema's minLength, which is what keeps the generic path schema-valid.
_STRINGS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("company", "employer", "organisation", "organization"), "Northwind Analytics"),
    (("role", "title", "position"), "Data Platform Engineer"),
    (("location", "city"), "Seattle, WA"),
    (("dates", "date", "period"), "Jun 2025 - Present"),
    (("name", "full_name", "candidate"), "John Doe"),
    (("email",), "demo@applination.app"),
    (("phone",), "+1-555-0100"),
    (("school", "university", "institution"), "Cascadia State University"),
    (("degree",), "B.S. Computer Science"),
    (("group", "category"), "Languages"),
    (("summary", "objective", "bio", "one_liner"),
     "Data platform engineer who likes the unglamorous half of reliability work."),
    (("keyword", "keywords", "skill", "skills", "items", "tag", "tags", "ats"),
     "Python"),
    (("bullet", "bullets", "highlight", "highlights", "achievements"),
     "Cut event loss from 4% to under 0.1% by moving retries onto a "
     "dedicated queue, raising pipeline throughput about 30%."),
    (("reason", "rationale", "critique", "feedback", "notes"),
     "Grounded in real experience and specific about the outcome."),
    (("body", "content", "text", "answer", "story"),
     "At Northwind Analytics I owned a batch pipeline that was quietly "
     "dropping about 4% of its events. Two weeks of reading the retry path "
     "turned up a re-enqueue onto an already saturated partition. Fixing it "
     "raised throughput roughly 30%, and the alert I added afterwards is the "
     "part I am actually proud of."),
)


def _string_for(key: str, schema: dict) -> str:
    lowered = (key or "").lower()
    value = "Sample demo content."
    for names, candidate in _STRINGS:
        if any(n in lowered for n in names):
            value = candidate
            break
    minimum = int(schema.get("minLength", 0) or 0)
    maximum = int(schema.get("maxLength", 0) or 0)
    if minimum and len(value) < minimum:
        # Pad with real words rather than repeated characters: some of these
        # land in rendered documents, and "aaaa..." in a demo resume is worse
        # than a slightly long sentence.
        filler = (
            " Measured the result, wrote it down, and left the runbook better "
            "than it was found."
        )
        while len(value) < minimum:
            value += filler
    if maximum and len(value) > maximum:
        value = value[: maximum - 1].rstrip() + "."
    return value
```

- [ ] **Step 6: Register it in the factory**

In `src/providers/factory.py`, add this branch immediately before the `raise ValueError` at the end of `get_provider` (around line 140):

```python
    if name == "demo":
        # Simulated responses for the shared demo account. It takes no API key
        # by design: see src/providers/demo_provider.py.
        from .demo_provider import DemoProvider
        return DemoProvider(fixtures_dir=sub.get("fixtures_dir") or None)
```

And extend the error message on the following line so an unknown-provider typo lists it:

```python
    raise ValueError(
        f"Unknown provider '{name}'. Options: claude, gemini, ollama, nim, "
        f"openrouter, deepseek, mistral, demo."
    )
```

- [ ] **Step 7: Run the tests**

Run: `python -m pytest tests/test_demo_provider.py -v`
Expected: PASS, all cases.

- [ ] **Step 8: Confirm nothing else regressed**

Run: `python -m pytest -q`
Expected: PASS. `tests/test_factory_warn_dedup.py` exercises `get_provider` failure paths and must be unaffected.

- [ ] **Step 9: Commit**

```bash
git add src/providers/demo_provider.py src/providers/factory.py demo_data/llm tests/test_demo_provider.py requirements.txt
git commit -m "feat(demo): add a DemoProvider that answers from committed fixtures"
```

---

### Task 2: The demo persona's master data and config

**Files:**
- Create: `demo_data/config.yaml`
- Create: `demo_data/master_data/resume.yaml`, `demo_data/master_data/bio.md`
- Create: `demo_data/master_data/stories/{pipeline-event-loss,oncall-dashboard,capstone-scheduler,ta-mentoring,hackathon-transit}.md`
- Create: `demo_data/master_data/cover_letters/examples/{northwind-internship,trellis-platform}.md`
- Test: `tests/test_demo_fixture.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: a fixture tree Task 4's `seed_demo()` copies verbatim. `resume.yaml` must satisfy `src/profile.derive_profile()` and `src/reference_loader`'s story frontmatter contract (`tags`, `role_fit`, `company_fit`, `one_liner`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_demo_fixture.py`:

```python
"""The committed demo fixture has to be loadable by the real loaders, and it
has to stay fictional — this repository is public."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo_data"


def test_fixture_exists():
    assert (DEMO / "config.yaml").is_file()
    assert (DEMO / "master_data" / "resume.yaml").is_file()
    assert (DEMO / "master_data" / "bio.md").is_file()


def test_config_routes_to_the_demo_provider_and_carries_no_keys():
    cfg = yaml.safe_load((DEMO / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["llm"]["primary"] == "demo"
    assert not cfg["llm"].get("fallbacks")
    # A committed api_key in a public repo is the failure this asserts against.
    for name, block in cfg["llm"].items():
        if isinstance(block, dict):
            assert not block.get("api_key"), f"llm.{name}.api_key must be empty"


def test_profile_derives_from_the_demo_resume():
    from src.profile import derive_profile

    master = yaml.safe_load(
        (DEMO / "master_data" / "resume.yaml").read_text(encoding="utf-8")
    )
    profile = derive_profile(master)
    assert profile["identity_titles"]
    assert profile["seniority"] in {"student", "new-grad", "professional"}


def test_stories_have_the_frontmatter_the_matcher_needs():
    from src.reference_loader import load_stories

    stories = load_stories(DEMO / "master_data" / "stories")
    assert len(stories) >= 5
    for story in stories:
        assert story.get("tags"), story
        assert story.get("one_liner"), story


@pytest.mark.parametrize("field", ["email", "phone"])
def test_contact_details_are_reserved_examples(field):
    cfg = yaml.safe_load((DEMO / "config.yaml").read_text(encoding="utf-8"))
    value = str(cfg["user"][field])
    assert "555-0100" in value or value.endswith("@applination.app")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_demo_fixture.py -v`
Expected: FAIL — `assert (DEMO / "config.yaml").is_file()`.

- [ ] **Step 3: Check the real signature of the story loader before writing fixtures**

Run: `python -c "import inspect, src.reference_loader as r; print(inspect.signature(r.load_stories)); print(inspect.getsource(r.load_stories)[:900])"`

If `load_stories` does not take a directory argument, adjust the test in Step 1 to call it the way the codebase does (for example by pointing `UserPaths.stories_dir` at the fixture) rather than changing the loader. **Do not change `src/reference_loader.py` in this task** — the fixture conforms to the loader, not the other way round.

- [ ] **Step 4: Write `demo_data/config.yaml`**

Copy `config.example.yaml` and change exactly these blocks, leaving its comments intact:

```yaml
user:
  full_name: "John Doe"
  email: "demo@applination.app"
  phone: "+1-555-0100"
  location: "Seattle, WA"
  linkedin: "https://www.linkedin.com/in/john-doe-demo"
  github: "https://github.com/john-doe-demo"
  website: ""

search:
  keywords: ["data engineer", "platform engineer", "backend engineer", "new grad"]
  min_match_score: 55
  max_jobs_per_day: 12
  locations: ["Seattle", "Remote", "San Francisco"]

llm:
  # The demo account never makes a real model call. `demo` serves committed
  # fixtures from demo_data/llm/ so every AI flow works without an API key —
  # see src/providers/demo_provider.py. No fallbacks: a fallback would be a
  # real provider, and reaching it would mean spending somebody's money.
  primary: "demo"
  fallbacks: []
  tasks: {}

inbox:
  enabled: false

reminders:
  digest_enabled: false
```

Delete every `api_key:` value from the provider blocks (leave the keys present and empty, so the Config page still renders the fields).

- [ ] **Step 5: Write `demo_data/master_data/resume.yaml`**

Model it on `master_data/templates/resume.yaml.example` (run `cat master_data/templates/resume.yaml.example` first and follow its exact key names — the renderer and `derive_profile` both depend on them). Content:

- **Education:** Cascadia State University, B.S. Computer Science, expected Jun 2026, GPA 3.7. Coursework: Distributed Systems, Databases, Algorithms, Machine Learning, Operating Systems.
- **Experience (invented employers):**
  - *Northwind Analytics* — Data Platform Intern, Seattle WA, Jun 2025 – Sep 2025. Bullets about the 4%-event-loss retry bug, the 30% throughput gain, and the alerting added afterwards.
  - *Trellis Labs* — Software Engineering Intern, Remote, Jan 2025 – May 2025. Bullets about the on-call triage dashboard that halved median triage time.
  - *Cascadia State University* — Teaching Assistant, Data Structures, Sep 2024 – Present. Bullets about 120 students and weekly sections.
- **Projects:** a course-scheduling capstone (constraint solver, 400 students), a transit-delay predictor from a hackathon.
- **Skills:** Python, Go, SQL, TypeScript; Postgres, Kafka, Redis; Docker, Kubernetes, Terraform, AWS; pytest, Airflow, dbt.

Every bullet: past tense, a number where honest, **no em dashes** (`src/tailor.py` strips them; a fixture that contains them is inconsistent with generated output).

- [ ] **Step 6: Write `demo_data/master_data/bio.md`**

Six to ten sentences of first-person voice reference — how John writes, not what he did. Plain, specific, allergic to promotional language. This file is injected into cover-letter prompts as a tone reference, so it should sound like `demo_data/llm/cover_letter.txt`.

- [ ] **Step 7: Write the five stories**

Each file follows the frontmatter contract in `master_data/stories/_INDEX.md` (read it first: `cat master_data/stories/_INDEX.md`) and uses only tags from that taxonomy:

| File | One-liner |
|---|---|
| `pipeline-event-loss.md` | Found a 4% silent event loss nobody had noticed for months. |
| `oncall-dashboard.md` | Halved on-call triage time by watching what engineers actually checked first. |
| `capstone-scheduler.md` | Built a course scheduler for 400 students under a hard constraint budget. |
| `ta-mentoring.md` | Taught data structures to 120 students and learned to explain rather than assert. |
| `hackathon-transit.md` | Shipped a transit-delay predictor in 36 hours and cut its scope twice. |

- [ ] **Step 8: Write the two example cover letters**

`demo_data/master_data/cover_letters/examples/*.md`, each with YAML frontmatter (`company`, `role`, `tags`) followed by a body, matching the format `src/reference_loader.match_example_letter()` expects. Confirm that format first: `python -c "import inspect, src.reference_loader as r; print(inspect.getsource(r.match_example_letter))"`.

- [ ] **Step 9: Run the tests**

Run: `python -m pytest tests/test_demo_fixture.py -v`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add demo_data tests/test_demo_fixture.py
git commit -m "feat(demo): add the John Doe persona fixture (config, resume, bio, stories)"
```

---

### Task 3: `server/demo.py` — the seeder

**Files:**
- Create: `server/demo.py`
- Create: `demo_data/seed.json`
- Test: `tests/test_demo_seed.py`

**Interfaces:**
- Consumes: `server.db.session`, `server.db.TENANT_MODELS`, `server.db.User`, `server.auth.hash_password`, `server.user_paths.user_paths`, `server.user_paths.USERS_DIR`.
- Produces:
  - `DEMO_EMAIL: str`
  - `demo_enabled() -> bool`
  - `is_demo_user(user: object) -> bool`
  - `ensure_demo_user() -> int` (returns the demo user's id)
  - `seed_demo(*, reset: bool = True) -> int` (returns the id; wipes and repopulates)
  Tasks 4, 5 and 6 import all five.

- [ ] **Step 1: Write the failing test**

Create `tests/test_demo_seed.py`:

```python
"""The seeder is the only thing standing between a shared demo account and
permanent vandalism, so idempotency and completeness of the wipe are the two
properties worth testing."""
from __future__ import annotations

import pytest
from sqlmodel import select

from server import demo as demo_mod
from server.db import Application, Run, User, session


def _counts() -> dict[str, int]:
    with session() as s:
        return {
            "runs": len(s.exec(select(Run)).all()),
            "apps": len(s.exec(select(Application)).all()),
        }


def test_ensure_creates_the_account_once(db):
    first = demo_mod.ensure_demo_user()
    second = demo_mod.ensure_demo_user()
    assert first == second
    with session() as s:
        rows = s.exec(select(User).where(User.email == demo_mod.DEMO_EMAIL)).all()
    assert len(rows) == 1


def test_seed_populates_rows_and_files(db):
    user_id = demo_mod.seed_demo()
    counts = _counts()
    assert counts["runs"] >= 1
    assert counts["apps"] >= 8

    from server.user_paths import user_paths

    paths = user_paths(user_id)
    assert paths.config_path.is_file()
    assert paths.resume_path.is_file()
    assert list(paths.stories_dir.glob("*.md"))


def test_seed_is_idempotent(db):
    demo_mod.seed_demo()
    first = _counts()
    demo_mod.seed_demo()
    assert _counts() == first


def test_seed_wipes_visitor_damage(db):
    user_id = demo_mod.seed_demo()
    with session() as s:
        # noscope: test fixture writing as the known demo user.
        s.add(Application(
            user_id=user_id, company="Vandalism Inc", title="junk",
            folder_path="/tmp/junk",
        ))
        s.commit()
    demo_mod.seed_demo()
    with session() as s:
        junk = s.exec(
            select(Application).where(Application.company == "Vandalism Inc")
        ).all()
    assert junk == []


def test_seed_rebases_dates_so_the_demo_never_looks_stale(db):
    from datetime import datetime

    demo_mod.seed_demo()
    with session() as s:
        runs = s.exec(select(Run)).all()
    newest = max(r.started_at for r in runs)
    assert (datetime.utcnow() - newest).days < 7


def test_is_demo_user(db):
    user_id = demo_mod.ensure_demo_user()
    with session() as s:
        user = s.get(User, user_id)
        assert demo_mod.is_demo_user(user)
```

Check how existing suites obtain a migrated database before running this — `grep -n "def db" tests/conftest.py`. If the fixture there is named something other than `db`, rename the parameter in every test above to match. Do not add a second database fixture.

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_demo_seed.py -v`
Expected: FAIL — `ImportError: cannot import name 'demo' from 'server'`.

- [ ] **Step 3: Write `demo_data/seed.json`**

Structure (all timestamps are **relative offsets**, never absolute):

```json
{
  "runs": [
    {
      "key": "run-recent",
      "days_ago": 1,
      "duration_minutes": 7,
      "status": "success",
      "jobs_found": 214,
      "applications_created": 5
    },
    {
      "key": "run-older",
      "days_ago": 8,
      "duration_minutes": 9,
      "status": "success",
      "jobs_found": 198,
      "applications_created": 4
    }
  ],
  "applications": [
    {
      "run": "run-recent",
      "company": "Stripe",
      "title": "Software Engineer, New Grad",
      "location": "Seattle, WA",
      "url": "https://stripe.com/jobs",
      "source": "greenhouse",
      "match_score": 88,
      "match_reason": "Payments infrastructure work maps onto the pipeline reliability experience.",
      "folder": "Stripe_Software_Engineer_New_Grad",
      "status": "applied",
      "applied_days_ago": 1,
      "deadline_in_days": 12,
      "tags": "priority,infra",
      "notes": ""
    }
  ],
  "ranked_jobs": [],
  "chat_sessions": [],
  "saved_answers": []
}
```

Fill it out to: **2 runs**; **12 applications** spanning every value of `ApplicationStatus` (run `python -c "from server.db import ApplicationStatus; print([s.value for s in ApplicationStatus])"` and cover each at least once), of which 4 carry a `folder` that exists under `demo_data/output/` (Task 4 creates those); **~20 ranked_jobs** across both runs with `selected` true for the ones that became applications, two `dismissed: true`, and the rest spread from 38 to 84 so the triage tab has range; **2 chat_sessions** (one `mode: "chat"`, one `mode: "interview"`) each with 4 messages alternating `user`/`assistant`, reusing the prose from `demo_data/llm/`; **3 saved_answers**.

Companies must be real, publicly-hiring firms (Stripe, Datadog, Snowflake, Cloudflare, Databricks, Figma…) — they appear only as postings, which is what they are.

- [ ] **Step 4: Write the seeder**

Create `server/demo.py`:

```python
"""The shared demo account, and the seeder that keeps it presentable.

Applination cannot otherwise be shown to anyone: every account is BYOK and
every account's data is personal and gitignored. So one account, ``John Doe``,
is committed as a fixture under ``demo_data/`` and seeded into an ordinary
user id at runtime.

Two decisions worth not re-litigating:

* **The account is identified by a constant email, not a database column.** A
  ``User.is_demo`` flag would cost an Alembic migration and a schema change to
  express a fact that is a single known identity.
* **The demo is fully writable and restored nightly.** A read-only demo of an
  interactive product demonstrates nothing. The re-seed is the mitigation, and
  it is only a mitigation because ``scripts/seed_demo.py`` runs from cron.

Every query here carries ``# noscope:``. That is not a loophole: the seeder
runs outside any request, against a user id it resolved itself from a
constant, and the scoping helpers exist to bind a query to *the caller*, which
here does not exist.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from sqlmodel import delete, select

from .auth import hash_password, normalize_email
from .db import (
    Application,
    ApplicationStatus,
    ChatMessage,
    ChatSession,
    RankedJob,
    Run,
    RunStatus,
    SavedAnswer,
    Setting,
    User,
    session,
)
from .user_paths import user_paths

log = logging.getLogger("server.demo")

ROOT = Path(__file__).resolve().parent.parent
DEMO_DATA = ROOT / "demo_data"

DEMO_EMAIL = normalize_email(
    os.environ.get("DEMO_EMAIL") or "demo@applination.app"
)


def demo_enabled() -> bool:
    """Whether to advertise and accept demo logins.

    Off if the fixture is absent (someone stripped it from a fork) or if the
    operator set ``DEMO_ENABLED=0`` — a private deployment should not carry a
    door with no lock on it.
    """
    if (os.environ.get("DEMO_ENABLED") or "").strip() == "0":
        return False
    return (DEMO_DATA / "config.yaml").is_file()


def is_demo_user(user: object) -> bool:
    return normalize_email(getattr(user, "email", "") or "") == DEMO_EMAIL


def ensure_demo_user() -> int:
    """Return the demo user's id, creating the account if it is absent.

    The password is random and discarded. Nobody signs in with it — the entry
    point is ``POST /api/auth/demo`` — but leaving the column empty would make
    this row a special case for every code path that reads it, including
    ``verify_password``.
    """
    with session() as s:
        # noscope: resolving the demo account itself, outside any request.
        # There is no caller to scope to; the constant email IS the predicate.
        user = s.exec(select(User).where(User.email == DEMO_EMAIL)).first()
        if user is None:
            user = User(
                email=DEMO_EMAIL,
                password_hash=hash_password(secrets.token_urlsafe(32)),
                is_owner=False,
            )
            s.add(user)
            s.commit()
            s.refresh(user)
            log.info("created demo account %s (id=%s)", DEMO_EMAIL, user.id)
        return int(user.id)  # type: ignore[arg-type]


def seed_demo(*, reset: bool = True) -> int:
    """Restore the demo account to the committed fixture. Idempotent."""
    user_id = ensure_demo_user()
    if reset:
        _wipe(user_id)
    _seed_files(user_id)
    _seed_rows(user_id)
    log.info("demo account %s seeded", user_id)
    return user_id


def _wipe(user_id: int) -> None:
    """Delete the demo user's rows and files. Order matters: ChatMessage and
    SavedAnswer carry foreign keys into ChatSession and Application."""
    ordered = (
        ChatMessage, SavedAnswer, ChatSession, RankedJob,
        Application, Run, Setting,
    )
    with session() as s:
        for model in ordered:
            # noscope: bulk delete of the demo account's own rows, keyed by the
            # id ensure_demo_user() resolved from the constant email.
            s.exec(delete(model).where(model.user_id == user_id))
        s.commit()

    root = user_paths(user_id).root
    if root.exists():
        shutil.rmtree(root)


def _seed_files(user_id: int) -> None:
    paths = user_paths(user_id).ensure()
    shutil.copy2(DEMO_DATA / "config.yaml", paths.config_path)
    shutil.copytree(
        DEMO_DATA / "master_data", paths.master_dir, dirs_exist_ok=True
    )
    src_output = DEMO_DATA / "output"
    if src_output.is_dir():
        # The fixture stores folders without a date component; the run they
        # belong to is dated relative to now, so the tree has to be placed
        # under the matching rebased day or folder_rel points at nothing.
        day = _day_root_for(_fixture()["runs"][0])
        dest = paths.default_output_dir / day
        dest.mkdir(parents=True, exist_ok=True)
        for folder in src_output.iterdir():
            if folder.is_dir():
                shutil.copytree(folder, dest / folder.name, dirs_exist_ok=True)


def _fixture() -> dict:
    return json.loads((DEMO_DATA / "seed.json").read_text(encoding="utf-8"))


def _ago(days: float) -> datetime:
    return datetime.utcnow() - timedelta(days=days)


def _day_root_for(run: dict) -> str:
    return _ago(run.get("days_ago", 0)).strftime("%Y-%m-%d")


def _seed_rows(user_id: int) -> None:
    data = _fixture()
    paths = user_paths(user_id)

    with session() as s:
        run_ids: dict[str, int] = {}
        for spec in data.get("runs", []):
            started = _ago(spec.get("days_ago", 0))
            run = Run(
                user_id=user_id,
                started_at=started,
                finished_at=started + timedelta(
                    minutes=spec.get("duration_minutes", 6)
                ),
                status=RunStatus(spec.get("status", "success")),
                jobs_found=spec.get("jobs_found", 0),
                applications_created=spec.get("applications_created", 0),
                day_root=started.strftime("%Y-%m-%d"),
            )
            s.add(run)
            s.commit()
            s.refresh(run)
            run_ids[spec["key"]] = int(run.id)  # type: ignore[arg-type]

        app_ids: dict[str, int] = {}
        for spec in data.get("applications", []):
            run_id = run_ids.get(spec.get("run", ""))
            day = _ago(
                next(
                    r["days_ago"] for r in data["runs"]
                    if r["key"] == spec["run"]
                )
            ).strftime("%Y-%m-%d")
            folder = spec.get("folder") or ""
            folder_rel = f"{day}/{folder}" if folder else ""
            app = Application(
                user_id=user_id,
                run_id=run_id,
                company=spec["company"],
                title=spec["title"],
                location=spec.get("location", ""),
                url=spec.get("url", ""),
                source=spec.get("source", ""),
                match_score=spec.get("match_score", 0),
                match_reason=spec.get("match_reason", ""),
                dedupe_key=_dedupe_key(spec["company"], spec["title"]),
                folder_path=str(paths.default_output_dir / folder_rel),
                folder_rel=folder_rel,
                resume_file=spec.get("resume_file", ""),
                cover_file=spec.get("cover_file", ""),
                status=ApplicationStatus(spec.get("status", "generated")),
                description=spec.get("description", ""),
                notes=spec.get("notes", ""),
                tags=spec.get("tags", ""),
                applied_at=(
                    _ago(spec["applied_days_ago"])
                    if "applied_days_ago" in spec else None
                ),
                deadline=(
                    _ago(-spec["deadline_in_days"])
                    if "deadline_in_days" in spec else None
                ),
                interview_at=(
                    _ago(-spec["interview_in_days"])
                    if "interview_in_days" in spec else None
                ),
                created_at=_ago(
                    next(
                        r["days_ago"] for r in data["runs"]
                        if r["key"] == spec["run"]
                    )
                ),
            )
            s.add(app)
            s.commit()
            s.refresh(app)
            app_ids[f"{spec['company']}|{spec['title']}"] = int(app.id)

        for spec in data.get("ranked_jobs", []):
            s.add(RankedJob(
                user_id=user_id,
                run_id=run_ids[spec["run"]],
                company=spec["company"],
                title=spec["title"],
                location=spec.get("location", ""),
                url=spec.get("url", ""),
                source=spec.get("source", ""),
                description=spec.get("description", ""),
                remote=spec.get("remote", False),
                match_score=spec.get("match_score", 0),
                match_reason=spec.get("match_reason", ""),
                selected=spec.get("selected", False),
                dismissed=spec.get("dismissed", False),
                dedupe_key=_dedupe_key(spec["company"], spec["title"]),
                application_id=app_ids.get(f"{spec['company']}|{spec['title']}"),
                created_at=_ago(
                    next(
                        r["days_ago"] for r in data["runs"]
                        if r["key"] == spec["run"]
                    )
                ),
            ))

        for spec in data.get("chat_sessions", []):
            chat = ChatSession(
                user_id=user_id,
                title=spec.get("title", "New chat"),
                mode=spec.get("mode", "chat"),
                created_at=_ago(spec.get("days_ago", 1)),
                updated_at=_ago(spec.get("days_ago", 1)),
            )
            s.add(chat)
            s.commit()
            s.refresh(chat)
            for i, msg in enumerate(spec.get("messages", [])):
                s.add(ChatMessage(
                    user_id=user_id,
                    session_id=int(chat.id),  # type: ignore[arg-type]
                    role=msg["role"],
                    content=msg["content"],
                    meta=json.dumps({"provider": "demo"}),
                    created_at=_ago(spec.get("days_ago", 1)) + timedelta(minutes=i),
                ))

        for spec in data.get("saved_answers", []):
            s.add(SavedAnswer(
                user_id=user_id,
                title=spec.get("title", ""),
                prompt=spec.get("prompt", ""),
                content=spec["content"],
                tags=spec.get("tags", ""),
                created_at=_ago(spec.get("days_ago", 2)),
            ))

        s.commit()


def _dedupe_key(company: str, title: str) -> str:
    from src.scrapers import dedupe_key

    return dedupe_key(company, title)
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_demo_seed.py -v`
Expected: PASS.

If `RunStatus(...)` or `ApplicationStatus(...)` raises `ValueError`, the fixture used a status value the enum does not define — fix `seed.json`, not the enum.

- [ ] **Step 6: Verify the scope lint still passes**

Run: `python -m pytest tests/test_scope_lint.py -v`
Expected: PASS. If it flags `server/demo.py`, the `# noscope:` comment is more than 6 lines above its query (`NOSCOPE_WINDOW`) — move it adjacent.

- [ ] **Step 7: Commit**

```bash
git add server/demo.py demo_data/seed.json tests/test_demo_seed.py
git commit -m "feat(demo): seed the demo account from the committed fixture"
```

---

### Task 4: Generate and commit the demo's documents

**Files:**
- Create: `scripts/build_demo_output.py`
- Create: `demo_data/output/<4 folders>/` (generated, then committed)
- Modify: `demo_data/seed.json` (fill `resume_file` / `cover_file` for the four foldered applications)

**Interfaces:**
- Consumes: `seed_demo()` from Task 3; `DemoProvider` from Task 1 (via `llm.primary: demo`); `src.pipeline.run_pipeline`.
- Produces: committed `.docx`/`.pdf` under `demo_data/output/`, which `_seed_files()` copies. No new Python API.

- [ ] **Step 1: Write the generator script**

Create `scripts/build_demo_output.py`:

```python
"""Generate the demo account's committed documents. Run by hand, not at runtime.

The documents in demo_data/output/ are produced by the real renderer from the
real fixture, driven by the demo provider — not hand-made. That way they cannot
drift from what a visitor sees when they click "Generate" in the demo, which is
the one inconsistency a demo cannot afford.

    python scripts/build_demo_output.py

Then review the output and commit it.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.demo import DEMO_DATA, seed_demo  # noqa: E402
from server.deps import load_config  # noqa: E402
from server.user_paths import user_paths  # noqa: E402
from src.pipeline import run_pipeline  # noqa: E402

# The four postings whose folders are committed. Keep in sync with the
# `folder` values in demo_data/seed.json.
KEEP = 4


def main() -> int:
    user_id = seed_demo()
    paths = user_paths(user_id)
    cfg = load_config(user_id)

    run_pipeline(
        cfg,
        paths=paths,
        dry_run=False,
        no_pdf=False,
        no_cache=True,
        on_event=lambda ev: print(ev.get("message", ev), flush=True),
    )

    produced = sorted(
        (p for p in paths.default_output_dir.rglob("*") if p.is_dir()
         and (p / "resume.docx").is_file()),
    )[:KEEP]
    if not produced:
        print("no documents were produced; nothing to commit", file=sys.stderr)
        return 1

    dest_root = DEMO_DATA / "output"
    if dest_root.exists():
        shutil.rmtree(dest_root)
    dest_root.mkdir(parents=True)
    for folder in produced:
        # Committed without the date component: the seeder places them under a
        # rebased day so they never look stale.
        shutil.copytree(folder, dest_root / folder.name)
        print(f"committed {folder.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run it**

Run: `python scripts/build_demo_output.py`
Expected: the pipeline runs end to end against `DemoProvider` and prints four folder names. **This is also the real end-to-end test of Task 1** — if the tailoring graph rejects the synthesised JSON, fix `_synthesise` in `demo_provider.py`, not the schema.

If PDF conversion fails (no Word or LibreOffice), the `.docx` files still appear; re-run on a machine that has one before committing, because the demo's download buttons offer PDFs.

- [ ] **Step 3: Inspect what you are about to make public**

Run: `ls -R demo_data/output && du -sh demo_data/output`
Open one `resume.docx` and one `cover_letter.docx`. Confirm: the name is John Doe, the contact line is `demo@applination.app` / `+1-555-0100`, no real person's details appear anywhere, and the total is under ~3 MB.

- [ ] **Step 4: Wire the filenames into the fixture**

For each of the four applications in `demo_data/seed.json` that has a `folder`, set `"resume_file": "resume.docx"` and `"cover_file": "cover_letter.docx"` (match the actual filenames on disk). Add `resume.v2.docx` + `resume.v2.json` to **one** folder by running the tweak flow against it, so the application-detail version diff has two versions to compare:

```bash
python -m src.tweak "data/users/<demo_id>/output/<day>/<Folder>/resume.docx" "Lead with the pipeline reliability work" --provider demo
```

Then copy the resulting `resume.v2.*` into the matching `demo_data/output/<Folder>/`.

- [ ] **Step 5: Verify the seeder places them correctly**

Run: `python -m pytest tests/test_demo_seed.py -v`

Then add this test to `tests/test_demo_seed.py` and run it:

```python
def test_seeded_applications_point_at_real_documents(db):
    from pathlib import Path

    user_id = demo_mod.seed_demo()
    with session() as s:
        apps = s.exec(
            select(Application).where(Application.resume_file != "")
        ).all()
    assert apps, "no application carries a document"
    for app in apps:
        assert (Path(app.folder_path) / app.resume_file).is_file(), app.folder_path
```

Expected: PASS. A failure here means `folder_rel` and the on-disk day disagree.

- [ ] **Step 6: Commit**

```bash
git add scripts/build_demo_output.py demo_data/output demo_data/seed.json tests/test_demo_seed.py
git commit -m "feat(demo): commit generated resumes and cover letters for the demo account"
```

---

### Task 5: `POST /api/auth/demo` and the API flags

**Files:**
- Modify: `server/auth.py` (add `UserOut.is_demo`, the `/demo` route)
- Modify: `server/app.py:54-68` (`PUBLIC_PATHS`), `server/app.py:146-148` (`/api/health`)
- Modify: `server/limits.py` (exempt the demo user from the per-user LLM limit)
- Create: `scripts/seed_demo.py`
- Test: `tests/test_demo_api.py`

**Interfaces:**
- Consumes: `DEMO_EMAIL`, `demo_enabled()`, `is_demo_user()`, `ensure_demo_user()`, `seed_demo()` from Task 3; `create_session`, `_set_cookie`, `_to_out`, `LOGIN_LIMIT` from `server/auth.py` and `server/limits.py`.
- Produces: `POST /api/auth/demo -> UserOut`; `GET /api/health -> {"ok": bool, "demo": bool}`; `UserOut.is_demo: bool`. Tasks 6 and 7 consume all three.

- [ ] **Step 1: Write the failing test**

Create `tests/test_demo_api.py`:

```python
"""The demo door is public by necessity, so what it does and does not allow is
worth pinning down."""
from __future__ import annotations

from server.demo import DEMO_EMAIL


def test_health_advertises_the_demo(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["demo"] is True


def test_demo_login_needs_no_credentials_and_yields_a_session(client):
    res = client.post("/api/auth/demo")
    assert res.status_code == 200
    assert res.json()["email"] == DEMO_EMAIL
    assert res.json()["is_demo"] is True

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["is_demo"] is True


def test_demo_session_can_read_the_demo_data(client):
    client.post("/api/auth/demo")
    apps = client.get("/api/applications").json()
    rows = apps["items"] if isinstance(apps, dict) else apps
    assert len(rows) >= 8


def test_an_ordinary_account_is_not_flagged_as_demo(client):
    client.post(
        "/api/auth/signup",
        json={"email": "real@example.com", "password": "correct-horse-battery"},
    )
    assert client.get("/api/auth/me").json()["is_demo"] is False


def test_demo_is_refused_when_disabled(client, monkeypatch):
    from server import demo as demo_mod

    monkeypatch.setattr(demo_mod, "demo_enabled", lambda: False)
    assert client.post("/api/auth/demo").status_code == 404
    assert client.get("/api/health").json()["demo"] is False
```

Match the `client` fixture to whatever `tests/conftest.py` already provides (`grep -n "TestClient" tests/conftest.py`); do not introduce a second one. Check the real shape of `GET /api/applications` before asserting on it: `grep -n "def list_applications" -A 20 server/applications.py`.

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_demo_api.py -v`
Expected: FAIL — `KeyError: 'demo'` on the health assertion.

- [ ] **Step 3: Add `is_demo` to `UserOut`**

In `server/auth.py`, extend the model and its constructor (around lines 205-219):

```python
class UserOut(BaseModel):
    id: int
    email: str
    is_owner: bool
    is_demo: bool = False
    created_at: datetime


def _to_out(u: User) -> UserOut:
    from .demo import is_demo_user

    return UserOut(
        id=u.id,  # type: ignore[arg-type]
        email=u.email,
        is_owner=u.is_owner,
        is_demo=is_demo_user(u),
        created_at=u.created_at,
    )
```

The import is function-local on purpose: `server/demo.py` imports `hash_password` from this module, and a module-level import would be circular.

- [ ] **Step 4: Add the route**

In `server/auth.py`, after the `login` handler:

```python
@router.post("/demo", response_model=UserOut)
@limiter.limit(LOGIN_LIMIT)
def demo_login(request: Request, response: Response) -> UserOut:
    """Sign in to the shared demo account. No credentials, by design.

    Rate limited per IP with the same budget as login: there is no password to
    guess here, but the first call may seed the account, and that is expensive
    enough not to want it in a loop.
    """
    from .demo import demo_enabled, ensure_demo_user, seed_demo

    if not demo_enabled():
        # 404 rather than 403: on a deployment with the demo switched off, the
        # endpoint may as well not exist.
        raise HTTPException(404, "not found")

    with session() as s:
        # noscope: resolving the demo account by its constant email, the same
        # way login resolves an account before any tenant context exists.
        user = s.exec(select(User).where(User.email == DEMO_EMAIL)).first()
    if user is None:
        # First visitor on a fresh install: seed before letting them in, or
        # they land on an empty dashboard and the demo has done its opposite.
        seed_demo()
        with session() as s:
            # noscope: same constant-email resolution, after seeding.
            user = s.exec(select(User).where(User.email == DEMO_EMAIL)).first()
    if user is None or user.disabled:
        raise HTTPException(404, "not found")

    with session() as s:
        token = create_session(s, user.id)  # type: ignore[arg-type]
    out = _to_out(user)
    _set_cookie(response, token, request)
    log.info("demo session issued")
    return out
```

Add `from .demo import DEMO_EMAIL` — no: keep it inside the function alongside the others, and reference `DEMO_EMAIL` from that same local import:

```python
    from .demo import DEMO_EMAIL, demo_enabled, ensure_demo_user, seed_demo
```

`ensure_demo_user` is imported for symmetry with `seed_demo`; if the linter objects to it being unused, drop it from the import list.

- [ ] **Step 5: Make the route public and advertise it**

In `server/app.py`, add to `PUBLIC_PATHS` (after the `/api/auth/logout` entry):

```python
    # The demo account is the product's front door for anyone who has not
    # signed up. It takes no credentials, is rate limited per IP, and lands the
    # caller in an account that contains nothing but committed fixture data.
    "/api/auth/demo",
```

And replace the health handler:

```python
    @app.get("/api/health")
    def health() -> dict:
        from .demo import demo_enabled

        # The login page is unauthenticated and needs to know whether to offer
        # the demo link, and this is the only public endpoint it already calls.
        return {"ok": True, "demo": demo_enabled()}
```

- [ ] **Step 6: Exempt the demo from the per-user LLM limit**

In `server/limits.py`, replace `_user_or_ip`:

```python
def _user_or_ip(request: Request) -> str:
    """Rate-limit key: the authenticated user when there is one, else the IP.

    ``require_user`` stashes the id on request.state. The IP fallback matters
    for the unauthenticated routes and means a missing user can never turn into
    an *unlimited* key.

    The demo account is keyed by IP instead of by user. The per-user LLM limit
    exists to cap spend on a shared worker, and a demo call spends nothing —
    it is answered from a fixture. Keying it per user would let one visitor
    lock every other visitor out of an account they all share.
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id is not None and not getattr(request.state, "is_demo", False):
        return f"user:{user_id}"
    return f"ip:{get_remote_address(request)}"
```

And set the flag in `require_user` in `server/auth.py`:

```python
def require_user(request: Request) -> User:
    user = resolve_user(request)
    if user is None:
        raise HTTPException(401, "not authenticated")
    request.state.user_id = user.id
    # Read by limits._user_or_ip: the demo account is limited per IP, not per
    # user, because its LLM calls are simulated and cost nothing.
    from .demo import is_demo_user

    request.state.is_demo = is_demo_user(user)
    return user
```

- [ ] **Step 7: Write the CLI**

Create `scripts/seed_demo.py`:

```python
"""Restore the shared demo account to its committed fixture.

Run nightly from cron (see docs/DEPLOY-SEATTLE.md). The demo is fully writable
so it feels like real software; this is what undoes the consequences.

    python scripts/seed_demo.py           # wipe and re-seed
    python scripts/seed_demo.py --create  # create the account only, no wipe
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.demo import DEMO_EMAIL, demo_enabled, ensure_demo_user, seed_demo  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--create",
        action="store_true",
        help="only ensure the account exists; do not wipe or re-seed it",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    if not demo_enabled():
        print("demo is disabled (DEMO_ENABLED=0 or demo_data/ is missing)")
        return 1

    user_id = ensure_demo_user() if args.create else seed_demo()
    print(f"demo account {DEMO_EMAIL} ready (id={user_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 8: Run the tests**

Run: `python -m pytest tests/test_demo_api.py tests/test_authz.py tests/test_scope_lint.py -v`
Expected: PASS. `test_authz.py` matters here: adding a public path is exactly the kind of change that can open one by accident.

- [ ] **Step 9: Run the whole suite**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add server/auth.py server/app.py server/limits.py scripts/seed_demo.py tests/test_demo_api.py
git commit -m "feat(demo): add a public demo sign-in endpoint and a re-seed CLI"
```

---

### Task 6: The "try the demo" affordance on login and signup

**Files:**
- Modify: `web/lib/api.ts:115-135` (`CurrentUser.is_demo`, `health` return type, `api.demoLogin`)
- Modify: `web/components/auth-form.tsx:120-135` (the link, below the card)
- Test: manual — `web/` has no test runner configured (confirm with `cat web/package.json`; if a `test` script exists, add a component test instead of the manual check)

**Interfaces:**
- Consumes: `POST /api/auth/demo` and `GET /api/health -> {ok, demo}` from Task 5.
- Produces: `api.demoLogin(): Promise<CurrentUser>`; `CurrentUser.is_demo: boolean`. Task 7 consumes `is_demo`.

- [ ] **Step 1: Extend the API client**

In `web/lib/api.ts`, change the `CurrentUser` type and the `health` / add `demoLogin`:

```ts
export type CurrentUser = {
  id: number;
  email: string;
  is_owner: boolean;
  is_demo: boolean;
  created_at: string;
};
```

```ts
  health: () => http<{ ok: boolean; demo: boolean }>("/api/health"),
```

```ts
  demoLogin: () =>
    http<CurrentUser>("/api/auth/demo", { method: "POST" }),
```

Add `/api/auth/demo` to the `AUTH_PATHS` array at line 73, so a 401 from it does not trigger the global redirect-to-login:

```ts
const AUTH_PATHS = [
  "/api/auth/login",
  "/api/auth/signup",
  "/api/auth/demo",
  "/api/auth/me",
];
```

- [ ] **Step 2: Add the affordance to the auth form**

In `web/components/auth-form.tsx`, add the imports and state:

```tsx
import { useQuery } from "@tanstack/react-query";
```

Inside `AuthForm`, after the existing `useState` calls:

```tsx
  // Only offered when the server says a demo exists — a private deployment
  // sets DEMO_ENABLED=0 and this disappears rather than 404ing on click.
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    staleTime: 5 * 60 * 1000,
  });

  async function onDemo() {
    setError(null);
    setBusy(true);
    try {
      const user = await api.demoLogin();
      queryClient.setQueryData(["me"], user);
      await queryClient.invalidateQueries();
      router.replace("/");
    } catch {
      setError("The demo is unavailable right now.");
      setBusy(false);
    }
  }
```

Then, immediately **after** the closing `</Card>` and before the closing `</div>` of the wrapper, add:

```tsx
        {health?.demo && (
          <p className="mt-3 text-right text-xs text-muted-foreground">
            Just exploring?{" "}
            <button
              type="button"
              onClick={onDemo}
              disabled={busy}
              className="underline underline-offset-2 hover:text-foreground disabled:opacity-50"
            >
              Try the demo
            </button>
          </p>
        )}
```

The wrapper `div` is currently `flex min-h-screen items-center justify-center p-6`, which centres a single child. Change it to stack the card and the link:

```tsx
    <div className="flex min-h-screen flex-col items-center justify-center p-6">
      <Card className="w-full max-w-sm">
```

and give the paragraph `w-full max-w-sm` so it aligns to the card's right edge:

```tsx
          <p className="mt-3 w-full max-w-sm text-right text-xs text-muted-foreground">
```

- [ ] **Step 3: Verify it renders and works**

Run: `cd web && npm run build`
Expected: build succeeds with no type errors (`is_demo` is now required on `CurrentUser`; if anything else constructs that type, the build will say so — fix those call sites).

Then run the app (`.\scripts\dev.ps1`), open `http://localhost:3000/login`, and confirm: a small muted "Just exploring? Try the demo" sits below the card, right-aligned, visually subordinate to the Sign in button. Click it — you land on the dashboard with John Doe's data.

- [ ] **Step 4: Commit**

```bash
git add web/lib/api.ts web/components/auth-form.tsx
git commit -m "feat(web): offer the demo account beside the login and signup forms"
```

---

### Task 7: The "simulated AI" nudge

**Files:**
- Create: `web/components/demo-banner.tsx`
- Modify: `web/components/app-shell.tsx:353-360` (render the banner above the header)
- Modify: `web/components/ai-assist.tsx`, `web/components/coach/conversation-workspace.tsx`, `web/app/essay/page.tsx`, `web/app/run/page.tsx` (a `SimulatedChip`)

**Interfaces:**
- Consumes: `CurrentUser.is_demo` from Task 6.
- Produces: `<DemoBanner />` and `<SimulatedChip />`, both exported from `web/components/demo-banner.tsx`.

- [ ] **Step 1: Write the components**

Create `web/components/demo-banner.tsx`:

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { Sparkles, X } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const DISMISS_KEY = "applination.demo-banner-dismissed";

/** True when the current session is the shared demo account. */
export function useIsDemo(): boolean {
  const { data } = useQuery({ queryKey: ["me"], queryFn: api.me });
  return data?.is_demo ?? false;
}

/**
 * A standing reminder that the AI in this account is not real.
 *
 * It is dismissible but session-scoped rather than permanent: a visitor who
 * hides it and then returns to Coach an hour later should be told again, since
 * the whole point is that they not mistake a fixture for a model.
 */
export function DemoBanner() {
  const isDemo = useIsDemo();
  const [dismissed, setDismissed] = useState(true);

  useEffect(() => {
    try {
      setDismissed(sessionStorage.getItem(DISMISS_KEY) === "1");
    } catch {
      setDismissed(false);
    }
  }, []);

  if (!isDemo || dismissed) return null;

  return (
    <div className="flex shrink-0 items-center gap-2 border-b border-primary/20 bg-primary/10 px-4 py-2 text-xs text-foreground sm:px-6">
      <Sparkles className="size-3.5 shrink-0 text-primary" />
      <p className="min-w-0 flex-1">
        You are exploring the <strong>John Doe</strong> demo. Everything works,
        but AI responses are simulated rather than live model calls.{" "}
        <a href="/signup" className="underline underline-offset-2">
          Create an account
        </a>{" "}
        to use your own API keys.
      </p>
      <button
        type="button"
        aria-label="Dismiss"
        className="shrink-0 text-muted-foreground hover:text-foreground"
        onClick={() => {
          setDismissed(true);
          try {
            sessionStorage.setItem(DISMISS_KEY, "1");
          } catch {
            /* private mode; the banner simply returns next navigation */
          }
        }}
      >
        <X className="size-3.5" />
      </button>
    </div>
  );
}

/**
 * Point-of-use honesty. The banner can be dismissed and lives at the top of
 * the page; this sits next to the button that is about to "call a model".
 */
export function SimulatedChip({ className }: { className?: string }) {
  if (!useIsDemo()) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-primary",
        className,
      )}
      title="This account returns canned responses instead of calling a model."
    >
      <Sparkles className="size-2.5" />
      Simulated
    </span>
  );
}
```

`SimulatedChip` calls a hook after a conditional return in the snippet above — React forbids that. Write it as:

```tsx
export function SimulatedChip({ className }: { className?: string }) {
  const isDemo = useIsDemo();
  if (!isDemo) return null;
  return (/* …as above… */);
}
```

- [ ] **Step 2: Mount the banner**

In `web/components/app-shell.tsx`, add the import:

```tsx
import { DemoBanner } from "@/components/demo-banner";
```

and place it above the header in the main return (currently line ~356), inside the column that already holds the header:

```tsx
      <div className="flex h-svh min-w-0 flex-1 flex-col overflow-hidden">
        <DemoBanner />
        <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center …">
```

- [ ] **Step 3: Add the chip to the four AI surfaces**

Place `<SimulatedChip />` beside the primary action in each:

- `web/components/ai-assist.tsx` — next to the panel's heading.
- `web/components/coach/conversation-workspace.tsx` — in the header, beside the mode title. This covers both `/coach` and `/interview`, since both render it.
- `web/app/essay/page.tsx` — beside the "Draft" button.
- `web/app/run/page.tsx` — beside the "Start run" button.

Find each anchor with: `grep -n "Button" web/components/ai-assist.tsx | head`, and so on for the rest. Import with `import { SimulatedChip } from "@/components/demo-banner";`.

- [ ] **Step 4: Verify**

Run: `cd web && npm run build`
Expected: succeeds.

Then, with the app running: sign in via the demo link and confirm the banner appears once at the top and a "Simulated" chip appears on `/coach`, `/interview`, `/essay`, `/run` and the master-data AI panel. Sign out, sign in as a real account, and confirm **neither** appears.

- [ ] **Step 5: Commit**

```bash
git add web/components/demo-banner.tsx web/components/app-shell.tsx web/components/ai-assist.tsx web/components/coach/conversation-workspace.tsx web/app/essay/page.tsx web/app/run/page.tsx
git commit -m "feat(web): tell demo visitors that the AI responses are simulated"
```

---

### Task 8: Nightly re-seed and documentation

**Files:**
- Modify: `docs/DEPLOY-SEATTLE.md` (a cron section)
- Modify: `CLAUDE.md` (a "Demo account" section, and the `demo` provider in the `llm:` config list)
- Modify: `README.md` (a short "Try it" note)
- Create: `scripts/seed_demo_cron.sh`

**Interfaces:**
- Consumes: `scripts/seed_demo.py` from Task 5.
- Produces: no code API.

- [ ] **Step 1: Write the cron wrapper**

Create `scripts/seed_demo_cron.sh`:

```bash
#!/usr/bin/env bash
# Nightly restore of the shared demo account.
#
# The demo is deliberately writable so it behaves like real software; this is
# what makes that safe. Runs inside the app container so it sees the same
# database and the same data/users volume the server does.
set -euo pipefail

CONTAINER="${APPLINATION_CONTAINER:-applination-app}"

docker exec "$CONTAINER" python scripts/seed_demo.py
```

Run: `chmod +x scripts/seed_demo_cron.sh`

Confirm the container name first — `grep -n "container_name" deploy/*.yml docs/DEPLOY-SEATTLE.md | head` — and use the real one as the default.

- [ ] **Step 2: Document the cron in the deploy guide**

Add to `docs/DEPLOY-SEATTLE.md`, in the operations section:

````markdown
## Nightly demo re-seed

The demo account (`demo@applination.app`) is shared and fully writable, so
visitors can change anything in it. Restoring it nightly is what keeps that
from being a problem. On the NAS:

```bash
crontab -e
```

Add:

```
# Restore the shared demo account at 04:10 local, when nobody is looking at it.
10 4 * * * /path/to/applination/scripts/seed_demo_cron.sh >> /var/log/applination-demo-seed.log 2>&1
```

Verify by hand first:

```bash
./scripts/seed_demo_cron.sh
```

To turn the demo off entirely, set `DEMO_ENABLED=0` in the app container's
environment and restart: the login link disappears and `POST /api/auth/demo`
404s.
````

Use `docker exec`, not `docker compose exec` — commit `671b3f3` changed that throughout this document for a reason.

- [ ] **Step 3: Document it in CLAUDE.md**

Add a section after "Multi-user":

```markdown
## Demo account

A shared, committable demo account — persona **John Doe**,
`demo@applination.app` — lets anyone try the product without signing up. Entry
is `POST /api/auth/demo` (public, per-IP rate limited); the login page offers
it beside the form when `GET /api/health` reports `demo: true`.

- **`demo_data/`** is the committed fixture: `config.yaml`, `master_data/`,
  generated documents under `output/`, `seed.json` (runs, applications, ranked
  pool, chat history, saved answers) and `llm/` (canned model responses).
  Timestamps in `seed.json` are **relative offsets**, rebased at seed time —
  absolute dates would make the demo visibly rot.
- **`server/demo.py`** seeds that fixture into an ordinary `data/users/<id>/`
  tree and the tenant tables. Idempotent. The account is identified by the
  constant `DEMO_EMAIL`, not a DB column — there is no migration.
- **`src/providers/demo_provider.py`** answers every LLM call from
  `demo_data/llm/` fixtures, chosen by cues in the system prompt (`text_call`)
  or by fingerprinting the JSON schema (`json_call`, which receives no task
  name). Unknown schemas are synthesised from the schema itself, so a new task
  degrades to valid output instead of breaking the demo. The demo config sets
  `llm.primary: demo`, so **nothing else in `src/` knows the demo exists**.
- **The demo is fully writable and restored nightly** by
  `scripts/seed_demo.py`, run from cron (see `docs/DEPLOY-SEATTLE.md`). A
  read-only demo of an interactive product demonstrates nothing.
- The demo user is **exempt from the per-user LLM rate limit** (simulated calls
  cost nothing; a per-user limit on a shared account is a lockout). Per-IP
  limits still apply.
- `DEMO_ENABLED=0` disables the whole thing.
- **Everything in `demo_data/` is fictional** — the repository is public. The
  persona's employers and school are invented; real companies appear only as
  public job postings.
```

In the Configuration section's `llm:` bullet, add `demo` to the list of provider blocks.

- [ ] **Step 4: Add the README note**

Under the project description in `README.md`:

```markdown
### Try it without signing up

Every deployment carries a shared demo account (persona "John Doe") with a
populated dashboard, a history of runs, generated resumes and cover letters,
and a working Coach. Click **Try the demo** beside the login form. AI responses
in that account are simulated rather than live model calls, and it is restored
nightly.
```

- [ ] **Step 5: Verify the whole thing end to end**

Run:

```bash
python -m pytest -q
cd web && npm run build && cd ..
python scripts/seed_demo.py
```

Expected: suite passes, web builds, seeder prints `demo account demo@applination.app ready (id=N)`.

Then start the app and walk the demo as a visitor would: login page → Try the demo → dashboard has upcoming deadlines → `/applications` has a populated table and kanban → open one with documents and confirm the resume renders, the version diff shows two versions, and the cover letter is editable → `/coach` returns a simulated answer with the chip visible → `/runs` shows two runs and the ranked-jobs triage tab has scored jobs → `/stats` renders charts with data.

Any empty surface here is a fixture gap: fix `demo_data/seed.json` and re-run `python scripts/seed_demo.py`.

- [ ] **Step 6: Commit and open the PR**

```bash
git add docs/DEPLOY-SEATTLE.md CLAUDE.md README.md scripts/seed_demo_cron.sh
git commit -m "docs(demo): document the demo account and its nightly re-seed"
git push -u origin feat/demo-account
gh pr create --title "feat: add a John Doe demo account with simulated AI" --body "Closes #38 …"
```

Do **not** merge — `main` is protected and every merge auto-deploys to the Seattle NAS. The PR is for review.

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| 1. `demo_data/` fixture | 2 (text), 3 (`seed.json`), 4 (documents) |
| 2. Persona and public-repo hygiene | 2 (steps 5-8), 4 (step 3 review gate) |
| 3. `server/demo.py` seeder | 3, plus the CLI in 5 |
| 4. `DemoProvider` | 1 |
| 5. Entry point (`/api/auth/demo`, health, me) | 5 |
| 6. Web affordance and nudge | 6, 7 |
| 7. Rate-limit exemption | 5 (step 6) |
| 8. Nightly re-seed | 8 |
| Testing section | 1, 2, 3, 4 (step 5), 5 |

**Type consistency:** `seed_demo(*, reset=True) -> int`, `ensure_demo_user() -> int`, `demo_enabled() -> bool`, `is_demo_user(user) -> bool` are used identically in Tasks 3, 5 and 8. `CurrentUser.is_demo` (Task 6) matches `UserOut.is_demo` (Task 5). `api.health` returns `{ok, demo}` in Tasks 5 and 6 alike.

**Known verify-before-you-write points** — these are the places where the plan asserts something about existing code that the implementer must confirm rather than trust: `load_stories`'s signature (Task 2 step 3), `match_example_letter`'s frontmatter format (Task 2 step 8), the `db`/`client` fixture names in `tests/conftest.py` (Tasks 3 and 5 step 1), the `GET /api/applications` response shape (Task 5 step 1), and the deploy container name (Task 8 step 1).
