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
  real prompts (``tailor.write_cover_letter``, ``server/coach_context.py``).
* ``json_call`` gets a ``schema`` and *no task name* -- that is the actual
  signature in ``base.py``. So anything structured is synthesised from the
  schema itself rather than looked up. A fixture would have to be revised
  every time a prompt's schema changed, and a stale one fails as a JSON-parse
  error deep inside the tailoring graph, which is a miserable thing to debug
  in a demo. Walking the schema cannot go stale.
"""
from __future__ import annotations

import logging
import random
import re
import time
from pathlib import Path

from .base import LLMProvider

LOG = logging.getLogger(__name__)

# demo_data/ sits at the repository root, beside src/ and server/. It is a
# committed asset like master_data/guidelines, not per-user data -- so reading
# it here does not breach the rule that src/ never imports server/.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_FIXTURES = _REPO_ROOT / "demo_data" / "llm"

# Ordered: the first match wins, so the more specific cue must come first.
# "an interviewer running a mock interview" (the kickoff prompt) would
# otherwise be swallowed by "running a mock interview" (the per-turn prompt),
# and the interview would open by critiquing an answer nobody had given.
_TEXT_CUES: tuple[tuple[str, str], ...] = (
    ("cover letter body", "cover_letter.txt"),
    ("an interviewer running a mock interview", "interview_kickoff.txt"),
    ("running a mock interview", "interview_turn.txt"),
    ("drafting an application answer", "essay.txt"),
    ("you are coach", "coach.txt"),
)

_RANKING_IDX_RE = re.compile(r"^\s*\[(\d+)\]", re.M)


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
            # The ranker is the one caller that passes no schema: it asks for
            # {"scores": [{"idx", "score", "reason"}]} in prose and reads that
            # key directly (src/tailor.py rank_jobs -> _parse_scores).
            if "scores" in (system or ""):
                return self._ranking_response(user)
            return {}
        return _synthesise(schema, rng=self._rng)

    def _ranking_response(self, user: str) -> dict:
        """Score every ``[idx]`` the batch prompt listed.

        The count has to match the batch: ``_parse_scores`` is handed
        ``batch_size``, so a short list silently drops jobs from the run.
        """
        indices = [int(m) for m in _RANKING_IDX_RE.findall(user or "")]
        if not indices:
            indices = list(range(15))
        scores = []
        for i in indices:
            # Deterministic per index, so two demo runs are comparable in the
            # run-diff view, and spread across the default threshold of 55 so
            # the triage tab has both selected and rejected jobs to show.
            value = 38 + (i * 37) % 52
            scores.append(
                {
                    "idx": i,
                    "score": value,
                    "reason": (
                        "Strong overlap with the data-pipeline and reliability work."
                        if value >= 70
                        else "Partial match; the role leans on skills not evidenced."
                    ),
                }
            )
        return {"scores": scores}


def _synthesise(schema: dict, *, rng: random.Random, depth: int = 0):
    """Build a value that satisfies ``schema``.

    Strings are keyed off the property name so the output reads like a resume
    rather than like "string": a ``company`` gets a company, ``bullets`` get
    bullets of a plausible length.
    """
    if depth > 12:  # pathological or recursive schema guard
        return {}
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), "string")

    if "enum" in schema:
        return schema["enum"][0]

    if kind == "object" or "properties" in schema:
        props: dict = schema.get("properties") or {}
        # additionalProperties:False plus a required list means the object may
        # contain only what is declared; emitting every declared property is
        # both valid and more useful, since optional fields are what make the
        # rendered demo documents look complete.
        keys = list(props) or list(schema.get("required") or [])
        out = {}
        for key in keys:
            sub = props.get(key, {"type": "string"})
            out[key] = _synthesise_named(key, sub, rng=rng, depth=depth + 1)
        return out

    if kind == "array":
        item_schema = schema.get("items") or {"type": "string"}
        count = max(int(schema.get("minItems", 0)), 3)
        if schema.get("maxItems"):
            count = min(count, int(schema["maxItems"]))
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
    """Same as :func:`_synthesise`, but allowed to look at the property name.

    The enum check has to come first: an enum-constrained string is still
    ``type: "string"``, and naming it something like ``seniority`` would
    otherwise route it to the property-name hints and emit a value outside the
    enum.
    """
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    scalarish = (
        kind is None
        and "properties" not in schema
        and "items" not in schema
        and "enum" not in schema
    )
    if kind == "string" or scalarish:
        return _string_for(key, schema)
    if kind == "array" and (schema.get("items") or {}).get("type") == "string":
        item = schema.get("items") or {}
        count = max(int(schema.get("minItems", 0)), 3)
        if schema.get("maxItems"):
            count = min(count, int(schema["maxItems"]))
        return [_string_for(key, item) for _ in range(count)]
    return _synthesise(schema, rng=rng, depth=depth)


# Property-name hints, longest-intent first. Anything unmatched falls back to
# filler padded to the schema's minLength, which is what keeps the generic
# path schema-valid for a task nobody has written yet.
_STRINGS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("company", "employer", "organisation", "organization"), "Northwind Analytics"),
    (("role", "title", "position"), "Data Platform Engineer"),
    (("location", "city"), "Seattle, WA"),
    (("dates", "date", "period"), "Jun 2025 - Sep 2025"),
    (("full_name", "candidate", "name"), "John Doe"),
    (("email",), "demo@applination.app"),
    (("phone",), "+1-555-0100"),
    (("school", "university", "institution"), "Cascadia State University"),
    (("degree",), "B.S. Computer Science"),
    (("group", "category"), "Languages"),
    (
        ("summary", "objective", "bio", "one_liner"),
        "Data platform engineer who likes the unglamorous half of reliability work.",
    ),
    (
        ("keyword", "skill", "items", "tag", "ats"),
        "Python",
    ),
    (
        ("bullet", "highlight", "achievement", "line"),
        "Cut event loss from 4% to under 0.1% by moving retries onto a "
        "dedicated queue, raising pipeline throughput about 30%.",
    ),
    (
        ("reason", "rationale", "critique", "feedback", "note", "verdict"),
        "Grounded in real experience and specific about the outcome.",
    ),
    (
        ("body", "content", "text", "answer", "story"),
        "At Northwind Analytics I owned a batch pipeline that was quietly "
        "dropping about 4% of its events. Two weeks of reading the retry path "
        "turned up a re-enqueue onto an already saturated partition. Fixing it "
        "raised throughput roughly 30%, and the alert I added afterwards is "
        "the part I am actually proud of.",
    ),
)

# Padding for schemas with a minLength longer than the hint. Real words, not
# repeated characters: some of these land in rendered documents, and "aaaa..."
# in a demo resume is worse than a slightly long sentence.
_FILLER = (
    " Measured the result, wrote it down, and left the runbook better than it "
    "was found."
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
    while len(value) < minimum:
        value += _FILLER
    if maximum and len(value) > maximum:
        value = value[: maximum - 1].rstrip() + "."
    return value
