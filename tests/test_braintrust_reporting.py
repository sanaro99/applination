from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.braintrust_reporting import braintrust_scores, publish_editorial_experiment
from src.editorial_evaluation import EditorialEvaluationCase


def _case(*, cloud_safe: bool) -> EditorialEvaluationCase:
    return EditorialEvaluationCase(
        case_id="synthetic-case",
        master_resume={"summary_options": ["Engineer."]},
        job={"company": "Example", "title": "Engineer", "description": "Python"},
        user={"full_name": "Evaluation Candidate", "email": "candidate@example.invalid"},
        bio="Synthetic voice sample.",
        stories=[],
        expectations={"required_phrases": ["Python"]},
        cloud_safe=cloud_safe,
    )


def _record() -> dict:
    return {
        "case_id": "synthetic-case",
        "ok": True,
        "latency_ms": 120,
        "candidate": {"provider": "demo", "model": "fixture"},
        "prompt_versions": {"resume.content_plan": "1"},
        "resume": {"summary": "Engineer."},
        "cover_letter": "A grounded letter.",
        "scores": {
            "resume": {
                "grounding_passed": True,
                "unsupported_numbers": [],
                "missing_sections": [],
                "missing_core_skills": [],
                "rendered_pdf_pages": 1,
                "bullet_count": 4,
            },
            "cover_letter": {
                "validation_issues": [],
                "unsupported_numbers": [],
                "word_count": 220,
            },
            "expectations": {"passed": True},
        },
    }


def test_scores_flatten_hard_gates_to_numeric_values():
    scores = braintrust_scores(_record())
    assert scores["run_ok"] == 1.0
    assert scores["grounding_passed"] == 1.0
    assert scores["no_unsupported_numbers"] == 1.0
    assert scores["one_page"] == 1.0


def test_publisher_refuses_private_cases_before_initializing_client():
    initialized = False

    def init_experiment(**_kwargs):
        nonlocal initialized
        initialized = True

    with pytest.raises(ValueError, match="not marked cloud_safe"):
        publish_editorial_experiment(
            [_case(cloud_safe=False)],
            [_record()],
            project="evals",
            experiment_name="candidate",
            candidate={"model": "fixture"},
            init_experiment=init_experiment,
        )
    assert initialized is False


def test_publisher_logs_safe_case_and_returns_experiment_url():
    captured = {"init": None, "events": []}

    class Experiment:
        name = "candidate"

        def log(self, **event):
            captured["events"].append(event)

        def summarize(self):
            return SimpleNamespace(experiment_url="https://braintrust.example/experiment")

    def init_experiment(**kwargs):
        captured["init"] = kwargs
        return Experiment()

    result = publish_editorial_experiment(
        [_case(cloud_safe=True)],
        [_record()],
        project="evals",
        experiment_name="candidate",
        candidate={"model": "fixture"},
        init_experiment=init_experiment,
    )

    assert result["url"] == "https://braintrust.example/experiment"
    assert captured["init"]["set_current"] is False
    assert captured["events"][0]["metadata"]["prompt_versions"] == {
        "resume.content_plan": "1"
    }
    assert captured["events"][0]["scores"]["grounding_passed"] == 1.0
