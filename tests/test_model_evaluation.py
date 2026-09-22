from __future__ import annotations

from types import SimpleNamespace

import pytest

import src.model_evaluation as evaluation
from src.model_evaluation import (
    CURATED_CANDIDATES,
    EvaluationCase,
    GeminiBatchEvaluator,
    GroqBatchEvaluator,
    MAX_CASES,
    run_sync_evaluation,
)


@pytest.fixture()
def case():
    return EvaluationCase(
        case_id="acme-platform",
        candidate_profile="Built Python services and improved deployment reliability.",
        job={"company": "Acme", "title": "Platform Engineer", "description": "Python and cloud."},
    )


def test_sync_evaluation_uses_one_identical_schema_per_case(monkeypatch, case):
    calls = []

    class Provider:
        def json_call(self, system, prompt, max_tokens, *, schema):
            calls.append((system, prompt, max_tokens, schema))
            return {"fit_summary": "Strong Python fit.", "matched_evidence": [],
                    "missing_or_risky_requirements": [], "tailoring_actions": []}

    monkeypatch.setattr(evaluation, "get_provider", lambda *args, **kwargs: Provider())
    records = run_sync_evaluation({}, CURATED_CANDIDATES["gpt-oss"], [case])

    assert records[0]["ok"] is True
    assert records[0]["candidate"]["model"] == "openai/gpt-oss-120b"
    assert calls[0][2] == 900
    assert calls[0][3] == evaluation.EVALUATION_SCHEMA
    assert "Acme" in calls[0][1]


def test_sync_evaluation_rejects_batch_targets(case):
    with pytest.raises(ValueError, match="Batch candidates"):
        run_sync_evaluation({}, CURATED_CANDIDATES["gemini-batch"], [case])


def test_gemini_batch_submit_is_bounded_and_preserves_case_id(case):
    created = {}

    class Batches:
        def create(self, **kwargs):
            created.update(kwargs)
            return SimpleNamespace(name="batches/abc", state=SimpleNamespace(name="JOB_STATE_PENDING"))

    evaluator = GeminiBatchEvaluator("", client=SimpleNamespace(batches=Batches()))
    assert evaluator.submit([case], display_name="private-eval") == {
        "name": "batches/abc", "state": "JOB_STATE_PENDING",
    }
    assert created["model"] == "gemini-3.8-flash"
    assert created["src"][0]["metadata"] == {"case_id": "acme-platform"}
    assert created["src"][0]["config"]["response_json_schema"] == evaluation.EVALUATION_SCHEMA

    with pytest.raises(ValueError, match=str(MAX_CASES)):
        evaluator.submit([case] * (MAX_CASES + 1), display_name="too-many")


def test_groq_batch_submits_private_jsonl_and_collects_output(case):
    captured = {}

    class Files:
        def create(self, *, file, purpose):
            captured["payload"] = file.read().decode("utf-8")
            captured["purpose"] = purpose
            return SimpleNamespace(id="file-input")

        def content(self, _file_id):
            return SimpleNamespace(read=lambda: (
                b'{"custom_id":"acme-platform","response":{"body":{"choices":['
                b'{"message":{"content":"{\\"fit_summary\\": \\"good\\"}"}}]}}}\n'
            ))

    class Batches:
        def create(self, **kwargs):
            captured["batch"] = kwargs
            return SimpleNamespace(id="batch-123", status="validating")

        def retrieve(self, _name):
            return SimpleNamespace(id="batch-123", status="completed", output_file_id="file-output")

    evaluator = GroqBatchEvaluator("", client=SimpleNamespace(files=Files(), batches=Batches()))
    submitted = evaluator.submit([case], display_name="private-eval")

    assert submitted == {"name": "batch-123", "state": "validating"}
    assert captured["purpose"] == "batch"
    assert '"custom_id": "acme-platform"' in captured["payload"]
    assert captured["batch"]["completion_window"] == "24h"
    collected = evaluator.collect("batch-123")
    assert collected["state"] == "completed"
    assert collected["results"][0]["case_id"] == "acme-platform"
    assert "fit_summary" in collected["results"][0]["text"]
