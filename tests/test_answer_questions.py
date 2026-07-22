"""Grounding tests for Tailor.answer_questions (src/tailor.py).

This path previously shipped the master resume to NEITHER the prompt nor the
model while instructing it to "never be generic" — specificity demanded with
no facts supplied, which is a fabrication machine. These tests lock in the
grounding so a future prompt edit can't silently drop it again.

The provider is a fake that captures the prompt, so no network calls happen.
"""
from __future__ import annotations

import pytest

from src.tailor import Tailor


class _CapturingProvider:
    """Records the (system, user) prompt and returns a well-formed answer set."""

    name = "fake"

    def __init__(self, n_answers: int = 2):
        self.system = ""
        self.user = ""
        self.schema = None
        self._n = n_answers

    def json_call(self, system, user, max_tokens=2000, *, schema=None):
        self.system = system
        self.user = user
        self.schema = schema
        return {
            "answers": [
                {"question": f"q{i}", "answer": f"a{i}"} for i in range(self._n)
            ]
        }


MASTER = {
    "summary_options": ["Backend engineer focused on reliability."],
    "core_skills": ["Python", "Go", "PostgreSQL"],
    "skills": {"infra": ["Kubernetes", "Terraform"]},
    "experience": [
        {
            "company": "Acme Corp",
            "role": "Software Engineer",
            "start_date": "2022",
            "end_date": "2024",
            "bullets_all": ["Cut p99 latency 40% by reworking the write path."],
        }
    ],
    "education": [{"degree": "BS Computer Science", "school": "State University", "gpa": "3.8"}],
}

STORIES = [
    {
        "title": "The write-path rewrite",
        "one_liner": "Cut p99 latency 40%.",
        "body": "We were seeing timeouts under load. " * 40,
    }
]

JOB = {"company": "Globex", "title": "Backend Engineer", "description": "We use Rust and Kafka."}
USER = {"full_name": "Test Candidate"}


@pytest.fixture()
def tailor_and_provider():
    prov = _CapturingProvider()
    return Tailor({"answer_questions": [prov]}), prov


def test_returns_empty_for_no_questions(tailor_and_provider):
    tailor, prov = tailor_and_provider
    assert tailor.answer_questions([], JOB, USER, "bio", STORIES) == []
    assert prov.user == ""  # no LLM call made


def test_prompt_includes_the_master_resume_facts(tailor_and_provider):
    """The regression: real employers/skills/metrics must reach the prompt."""
    tailor, prov = tailor_and_provider
    tailor.answer_questions(
        ["Tell us about your backend experience.", "Why this role?"],
        JOB, USER, "I write plainly.", STORIES, master=MASTER,
    )

    assert "RESUME PROFILE" in prov.user
    # Employer, skills, a real metric and the degree all reach the model.
    assert "Acme Corp" in prov.user
    assert "Kubernetes" in prov.user
    assert "Cut p99 latency 40%" in prov.user
    assert "BS Computer Science" in prov.user


def test_prompt_carries_anti_fabrication_language(tailor_and_provider):
    tailor, prov = tailor_and_provider
    tailor.answer_questions(["Describe your Rust experience."], JOB, USER, "bio", STORIES, master=MASTER)

    # Grounding is stated as overriding, mirroring write_cover_letter/Coach.
    assert "GROUNDING" in prov.system
    assert "Never invent" in prov.system
    # The escape hatch is what stops "we use Rust" in the JD from inducing a
    # fabricated Rust claim — the model must be told honesty is an option.
    assert "haven't worked with" in prov.system
    # And the per-claim traceability rule reaches the user prompt.
    assert "BINDING" in prov.user
    assert "must trace to the RESUME" in prov.user


def test_positioning_block_present_only_with_profile(tailor_and_provider):
    tailor, prov = tailor_and_provider
    tailor.answer_questions(["Q?"], JOB, USER, "bio", STORIES, master=MASTER)
    assert "POSITIONING" not in prov.user

    tailor.answer_questions(
        ["Q?"], JOB, USER, "bio", STORIES, master=MASTER,
        profile={"identity_titles": ["Software Engineer"], "seniority": "professional"},
    )
    assert "POSITIONING" in prov.user
    assert "NEVER an 'internship'" in prov.user


def test_schema_is_passed_to_the_provider(tailor_and_provider):
    tailor, prov = tailor_and_provider
    tailor.answer_questions(["Q?"], JOB, USER, "bio", STORIES, master=MASTER)
    assert prov.schema is not None
    assert prov.schema["properties"]["answers"]["type"] == "array"


def test_missing_master_degrades_without_crashing(tailor_and_provider):
    """Callers that omit master still work; they just get a weaker prompt."""
    tailor, prov = tailor_and_provider
    out = tailor.answer_questions(["Q?"], JOB, USER, "bio", STORIES)
    assert len(out) == 1
    assert "(no resume data available)" in prov.user


def test_short_answer_list_pads_and_never_drops_questions():
    """A model returning fewer answers than questions must not silently lose one."""
    prov = _CapturingProvider(n_answers=1)
    tailor = Tailor({"answer_questions": [prov]})
    out = tailor.answer_questions(["Q1", "Q2", "Q3"], JOB, USER, "bio", STORIES, master=MASTER)
    assert [a["question"] for a in out] == ["q0", "Q2", "Q3"]
    assert out[1]["answer"] == "(generation failed)"


def test_provider_failure_returns_placeholders():
    class _Boom:
        name = "boom"

        def json_call(self, *a, **k):
            raise RuntimeError("provider down")

    tailor = Tailor({"answer_questions": [_Boom()]})
    out = tailor.answer_questions(["Q1", "Q2"], JOB, USER, "bio", STORIES, master=MASTER)
    assert [a["answer"] for a in out] == ["(generation failed)", "(generation failed)"]
