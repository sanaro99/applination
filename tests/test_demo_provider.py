"""The demo provider must be indistinguishable from a real one to callers.

Every flow in the app funnels through text_call/json_call. If the demo
provider can return something schema-invalid, the demo breaks in exactly the
places a visitor is most likely to click.
"""
from __future__ import annotations

import jsonschema
import pytest

from src.providers.demo_provider import DemoProvider
from src.providers.factory import get_provider
from src.schemas import (
    CRITIQUE_SCHEMA,
    KEYWORDS_SCHEMA,
    MASTER_RESUME_SCHEMA,
    RELINEFIT_SCHEMA,
    RESUME_SCHEMA,
    STORY_SCHEMA,
)


@pytest.fixture
def provider() -> DemoProvider:
    # No delay under test: the sleep exists for demo realism, and paying it in
    # the suite would add minutes for no assertion.
    return DemoProvider(delay=(0.0, 0.0))


def test_factory_builds_it_by_name():
    p = get_provider("demo", {"demo": {}})
    assert p.name == "demo"


def test_factory_error_message_lists_demo():
    with pytest.raises(ValueError, match="demo"):
        get_provider("nope", {})


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
        "Feedback: 2-3 sentences",
        "u",
    )
    for label in ("Feedback", "Model answer", "Next question"):
        assert label in out


def test_interview_kickoff_is_not_the_per_turn_response(provider):
    kickoff = provider.text_call(
        "You are Coach, an interviewer running a mock interview with John.", "u"
    )
    turn = provider.text_call(
        "You are Coach, running a mock interview with John.", "u"
    )
    assert kickoff != turn
    # A kickoff that opens with feedback would be feedback on nothing.
    assert "Feedback" not in kickoff


def test_unknown_text_prompt_still_returns_something(provider):
    out = provider.text_call("some prompt nobody planned for", "u")
    assert out.strip()


@pytest.mark.parametrize(
    "schema",
    [
        RESUME_SCHEMA,
        CRITIQUE_SCHEMA,
        RELINEFIT_SCHEMA,
        STORY_SCHEMA,
        MASTER_RESUME_SCHEMA,
        KEYWORDS_SCHEMA,
    ],
)
def test_known_schemas_validate(provider, schema):
    out = provider.json_call("sys", "user", schema=schema)
    jsonschema.validate(out, schema)


def test_ranking_call_has_no_schema_but_needs_scores(provider):
    # tailor.rank_jobs calls json_call WITHOUT a schema and parses resp["scores"].
    out = provider.json_call(
        'Return a JSON object with key "scores" containing an array', "u"
    )
    assert isinstance(out.get("scores"), list)
    assert {"idx", "score", "reason"} <= set(out["scores"][0])


def test_ranking_scores_every_job_in_the_batch(provider):
    # A short list silently drops jobs: _parse_scores is handed batch_size and
    # fills the gap with nothing.
    user = "\n".join(f"[{i}] Company {i} - Engineer" for i in range(23))
    out = provider.json_call('... key "scores" ...', user)
    assert [row["idx"] for row in out["scores"]] == list(range(23))


def test_ranking_spans_the_selection_threshold(provider):
    # The triage tab is empty unless some jobs fall below min_match_score and
    # some above it.
    user = "\n".join(f"[{i}] Company {i} - Engineer" for i in range(20))
    scores = [row["score"] for row in provider.json_call('"scores"', user)["scores"]]
    assert min(scores) < 55 <= max(scores)


def test_unknown_schema_is_synthesised_and_valid(provider):
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


def test_no_em_dashes_anywhere(provider):
    """src/tailor.py strips em dashes for ATS safety. A fixture containing one
    would render differently from everything else the pipeline produces."""
    texts = [
        provider.text_call("... 3-paragraph cover letter body ...", "u"),
        provider.text_call("You are Coach, a career assistant for John.", "u"),
        provider.text_call("You are Coach, running a mock interview", "u"),
        provider.text_call("You are Coach, drafting an application answer", "u"),
        provider.text_call("unmatched", "u"),
    ]
    for text in texts:
        assert "—" not in text
