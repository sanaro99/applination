import json

import pytest

from src.editorial_evaluation import (
    load_editorial_cases,
    run_editorial_evaluation,
    score_cover_letter,
    score_resume,
)
from src.model_evaluation import CURATED_CANDIDATES

from tests.test_evidence_pipeline import MASTER


def test_load_editorial_cases_requires_master_and_job(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps([{
        "id": "merge-and-ground",
        "master_resume": MASTER,
        "job": {"company": "Target", "title": "Backend Engineer", "description": "queues"},
        "stories": [],
    }]), encoding="utf-8")
    cases = load_editorial_cases(str(path))
    assert cases[0].case_id == "merge-and-ground"
    assert cases[0].user["full_name"] == "Evaluation Candidate"
    assert cases[0].expectations == {}


def test_resume_score_tracks_rewrite_layout_and_unsupported_numbers():
    resume = {
        "summary": "Backend engineer.", "skills": [], "education": [], "projects": [],
        "experience": [{
            "company": "Acme",
            "bullets": [
                MASTER["experience"][0]["bullets_all"][0],
                "Invented a 99% reliability result.",
            ],
        }],
    }
    metrics = {"audit": {"final_grounding": {"passed": False, "degraded": False}}}
    score = score_resume(resume, MASTER, metrics)
    assert score["verbatim_source_bullets"] == 1
    assert score["rewritten_bullet_ratio"] == 0.5
    assert score["unsupported_numbers"] == ["99%"]
    assert score["grounding_passed"] is False


def test_cover_letter_score_reports_shape_and_fabricated_number():
    letter = "First paragraph.\n\nA fabricated 99% result.\n\nProfessional close."
    score = score_cover_letter(letter, MASTER, [])
    assert score["paragraph_count"] == 3
    assert score["unsupported_numbers"] == ["99%"]


def test_editorial_eval_rejects_batch_candidate():
    with pytest.raises(ValueError, match="synchronous"):
        run_editorial_evaluation({}, CURATED_CANDIDATES["gemini-batch"], [])
