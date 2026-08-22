"""The demo provider must be indistinguishable from a real one to callers.

Every flow in the app funnels through text_call/json_call. If the demo
provider can return something schema-invalid, the demo breaks in exactly the
places a visitor is most likely to click.
"""
from __future__ import annotations

import json

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


def test_cover_letter_fixture_passes_the_real_validation_gate(provider):
    """write_cover_letter runs every draft through validate_cover_letter and
    falls back to a placeholder after three failures. That fallback is silent
    in the logs of a successful run, so the demo shipped placeholder letters
    once already: the fixture was 210 words against a 220-word floor."""
    from src.tailor import validate_cover_letter

    out = provider.text_call("... 3-paragraph cover letter body ...", "job")
    assert validate_cover_letter(out) == []


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


def test_resume_comes_from_the_fixture_not_the_walker(provider):
    """The tailored resume is the demo's centrepiece and gets a real fixture.
    The walker cannot know a GPA is "3.7/4.0" rather than a sentence, and it
    emitted three identical education entries because the schema only requires
    one. This test is also what keeps that fixture from going stale."""
    out = provider.json_call("sys", "user", schema=RESUME_SCHEMA)
    jsonschema.validate(out, RESUME_SCHEMA)
    assert len(out["education"]) == 1
    assert out["education"][0]["gpa"] == "3.7/4.0"
    # Consistent with demo_data/master_data/resume.yaml: a visitor who reads
    # the master data and then a generated resume must see the same person.
    assert {e["company"] for e in out["experience"]} == {
        "Northwind Analytics", "Trellis Labs", "Cascadia State University",
    }


def test_tweak_echoes_the_resume_back_with_a_real_edit(provider):
    """src/tweak.py calls json_call with no schema at all. Returning {} there
    silently emptied the tweak, and a tweak that changes nothing renders an
    empty version diff, which reads as broken rather than as simulated."""
    current = {
        "summary": "Original summary.",
        "skills": [{"group": "Languages", "items": ["Python"]}],
        "experience": [{"company": "Northwind Analytics", "role": "Intern",
                        "bullets": ["Did the thing."]}],
        "education": [{"school": "Cascadia State University", "degree": "BS"}],
        "ats_keywords": ["Python"],
    }
    prompt = (
        f"CURRENT RESUME JSON:\n{json.dumps(current, indent=2)}\n\n"
        "JOB:\nCompany: Sentry\n\nProduce the updated resume JSON now."
    )
    out = provider.json_call("You are an expert resume editor.", prompt)

    assert out["summary"] != current["summary"]
    # Everything else survives: a tweak must not quietly drop the resume.
    assert out["experience"] == current["experience"]
    assert out["education"] == current["education"]


def test_a_second_tweak_is_not_a_no_op(provider):
    once = provider.json_call(
        "You are an expert resume editor.",
        'CURRENT RESUME JSON:\n{"summary": "Original."}\n\nGo.',
    )
    twice = provider.json_call(
        "You are an expert resume editor.",
        f'CURRENT RESUME JSON:\n{json.dumps(once)}\n\nGo.',
    )
    assert twice["summary"] != once["summary"]


def test_relinefit_returns_no_rewrites(provider):
    """The line-fitter's Tier-2 rescue asks which bullets to rewrite. Invented
    answers overwrote two good project bullets with the same generic sentence
    in a real generated resume, so the honest simulated answer is "none"."""
    out = provider.json_call("sys", "user", schema=RELINEFIT_SCHEMA)
    jsonschema.validate(out, RELINEFIT_SCHEMA)
    assert out["rewrites"] == []


def test_critique_passes_cleanly(provider):
    """A fabricated critique can trigger a revise loop that rewrites a resume
    nobody complained about."""
    out = provider.json_call("sys", "user", schema=CRITIQUE_SCHEMA)
    jsonschema.validate(out, CRITIQUE_SCHEMA)
    assert out == {"issues": [], "severity": "none", "passed": True}


def test_zero_is_a_legal_integer_minimum(provider):
    """`int(minimum) or 3` treated `minimum: 0` as absent, which is how every
    entry in a rewrite list ended up pointing at index 3."""
    schema = {
        "type": "object",
        "properties": {"idx": {"type": "integer", "minimum": 0}},
        "required": ["idx"],
    }
    assert provider.json_call("s", "u", schema=schema)["idx"] == 0


def test_walker_does_not_give_education_the_internship_dates(provider):
    """An education entry and an experience entry both have a `dates` field.
    Keyed on the leaf name alone the walker gave both the same value, which
    printed the university with the internship's dates in a rendered resume.

    Exercised through a schema that deliberately does NOT match the resume
    fingerprint, so this covers the walker rather than the fixture.
    """
    entry = {
        "type": "object",
        "properties": {"dates": {"type": "string"}},
        "required": ["dates"],
    }
    schema = {
        "type": "object",
        "properties": {
            "education": {"type": "array", "items": entry, "minItems": 1},
            "experience": {"type": "array", "items": entry, "minItems": 1},
        },
        "required": ["education", "experience"],
    }
    out = provider.json_call("sys", "user", schema=schema)
    assert out["education"][0]["dates"] != out["experience"][0]["dates"]


def test_walker_summary_is_prose_not_padding(provider):
    """A hint shorter than the schema's minLength gets padded with filler, and
    the filler is what rendered at the top of the demo's resume."""
    schema = {
        "type": "object",
        "properties": {"summary": {"type": "string", "minLength": 80}},
        "required": ["summary"],
    }
    summary = provider.json_call("sys", "user", schema=schema)["summary"]
    assert len(summary) >= 80
    assert "left the runbook better than it was found" not in summary


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
