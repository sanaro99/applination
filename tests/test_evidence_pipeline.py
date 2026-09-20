from __future__ import annotations

from copy import deepcopy

from src.evidence import build_evidence_ledger, finalize_resume, normalize_content_plan
from src.providers.base import LLMProvider
from src.resume_pipeline import run_resume_editorial_pipeline


MASTER = {
    "summary_options": ["Backend engineer who improved a production queue and its reliability."],
    "core_skills": ["Python", "SQL"],
    "ats_adjacent_skills": ["MongoDB"],
    "skills": {"languages": ["Python", "SQL"], "data": ["PostgreSQL"]},
    "experience": [{
        "company": "Acme",
        "role": "Software Engineer",
        "location": "Remote",
        "start_date": "2022",
        "end_date": "Present",
        "bullets_all": [
            "Diagnosed retry contention in a PostgreSQL-backed job queue.",
            "Reduced failed jobs by 40% after isolating retries and adding idempotency checks.",
            "Added queue-depth alerts and wrote the responder runbook.",
        ],
    }, {
        "company": "Unrelated Co",
        "role": "Support Analyst",
        "start_date": "2020",
        "end_date": "2021",
        "bullets_all": ["Answered customer tickets."],
    }],
    "projects": [{
        "name": "Worker Lab",
        "tech": "Python, PostgreSQL",
        "bullets_all": ["Built a local queue simulator to test retry behavior."],
    }],
    "education": [{
        "school": "State University", "degree": "BS Computer Science",
        "start_date": "2016", "end_date": "2020", "coursework": ["Databases"],
    }],
}


def _plan():
    return {
        "role_strategy": "Lead with queue reliability.",
        "requirements": [{
            "id": "r1", "text": "Reliable backend systems", "priority": 5,
            "evidence_ids": ["experience.0.bullet.0", "experience.0.bullet.1"],
        }],
        "selected_experience": [{
            "source_id": "experience.0",
            "evidence_ids": [
                "experience.0.bullet.0", "experience.0.bullet.1", "experience.0.bullet.2",
            ],
            "target_bullets": 2, "highlight": True, "reason": "Direct backend evidence.",
        }],
        "selected_projects": [{
            "source_id": "project.0", "evidence_ids": ["project.0.bullet.0"],
            "target_bullets": 1, "highlight": False, "reason": "Relevant supporting project.",
        }],
        "selected_skills": [
            {"skill": "Python", "evidence_ids": ["skill.0"], "support": "direct"},
            {"skill": "SQL", "evidence_ids": ["skill.1"], "support": "direct"},
            {"skill": "PostgreSQL", "evidence_ids": ["skill.2"], "support": "direct"},
            {"skill": "MongoDB", "evidence_ids": ["adjacent_skill.0"], "support": "adjacent"},
        ],
        "summary_evidence_ids": ["summary.0", "experience.0.bullet.1"],
        "ats_keywords": ["Python", "backend", "reliability"],
    }


class _EditorialProvider(LLMProvider):
    name = "editorial-test"

    def __init__(self):
        self.calls = []

    def text_call(self, system: str, user: str, max_tokens: int = 1000) -> str:
        raise AssertionError("pipeline should use structured calls")

    def json_call(self, system: str, user: str, max_tokens: int = 2000, *, schema=None):
        required = set((schema or {}).get("required") or [])
        self.calls.append((required, system, user))
        if "role_strategy" in required:
            return _plan()
        if required == {"verdicts", "passed"}:
            return {
                "passed": True,
                "verdicts": [
                    {
                        "path": "summary", "claim": "Backend engineer focused on reliability.",
                        "support": "entailed", "evidence_ids": ["summary.0"],
                        "action": "accept", "reason": "Supported positioning.",
                    }, {
                        "path": "experience.0.bullets.0",
                        "claim": "Reduced failed jobs by 40% by fixing retry contention.",
                        "support": "entailed",
                        "evidence_ids": ["experience.0.bullet.0", "experience.0.bullet.1"],
                        "action": "accept",
                        "reason": "Faithfully merges two directly related source bullets.",
                    }, {
                        "path": "experience.0.bullets.1", "claim": "Added alerts and a runbook.",
                        "support": "direct", "evidence_ids": ["experience.0.bullet.2"],
                        "action": "accept", "reason": "Direct source support.",
                    }, {
                        "path": "projects.0.bullets.0", "claim": "Built a queue simulator.",
                        "support": "direct", "evidence_ids": ["project.0.bullet.0"],
                        "action": "accept", "reason": "Direct source support.",
                    }, {
                        "path": "skills.0.items.0", "claim": "Python",
                        "support": "direct", "evidence_ids": ["skill.0"],
                        "action": "accept", "reason": "Direct source support.",
                    }, {
                        "path": "skills.0.items.1", "claim": "SQL",
                        "support": "direct", "evidence_ids": ["skill.1"],
                        "action": "accept", "reason": "Direct source support.",
                    }, {
                        "path": "skills.1.items.0", "claim": "PostgreSQL",
                        "support": "direct", "evidence_ids": ["skill.2"],
                        "action": "accept", "reason": "Direct source support.",
                    }, {
                        "path": "skills.1.items.1",
                        "claim": "MongoDB (transferable familiarity)",
                        "support": "adjacent", "evidence_ids": ["skill.1", "skill.2"],
                        "action": "accept", "reason": "Qualified related database knowledge.",
                    },
                ],
            }
        return {
            "summary": "Backend engineer focused on reliable job processing and transferable data-system design.",
            "skills": [
                {"group": "Languages", "items": ["Python", "SQL"]},
                {"group": "Related Knowledge", "items": [
                    "PostgreSQL", "MongoDB (transferable familiarity)",
                ]},
            ],
            "experience": [{
                "company": "Acme", "role": "Software Engineer", "location": "Remote",
                "dates": "2022 - Present",
                "bullets": [
                    "Reduced failed jobs by 40% by diagnosing retry contention, isolating retries, and adding idempotency checks.",
                    "Added queue-depth alerts and documented the response path in an on-call runbook.",
                ],
            }, {
                "company": "Unrelated Co", "role": "Support Analyst",
                "bullets": ["Answered customer tickets."],
            }],
            "projects": [{
                "name": "Worker Lab", "tech": "Python, PostgreSQL", "link": "",
                "bullets": ["Built a local queue simulator to test retry behavior."],
            }],
            "education": [{"school": "State University", "degree": "BS Computer Science"}],
            "ats_keywords": ["Python", "backend", "reliability"],
        }


class _UnavailableVerifier(LLMProvider):
    name = "unavailable-verifier"

    def text_call(self, system: str, user: str, max_tokens: int = 1000) -> str:
        raise RuntimeError("offline")

    def json_call(self, system: str, user: str, max_tokens: int = 2000, *, schema=None):
        raise RuntimeError("offline")


def test_ledger_ids_are_stable_and_adjacent_is_explicit():
    first = build_evidence_ledger(MASTER)
    second = build_evidence_ledger(MASTER)
    assert [item.id for item in first] == [item.id for item in second]
    adjacent = next(item for item in first if item.id == "adjacent_skill.0")
    assert adjacent.text == "MongoDB"
    assert adjacent.support == "adjacent"


def test_finalize_respects_selection_and_requires_visible_adjacent_qualification():
    ledger = build_evidence_ledger(MASTER)
    job = {"title": "Backend Engineer", "description": "MongoDB data services"}
    plan = normalize_content_plan(_plan(), MASTER, job, ledger)
    draft = _EditorialProvider().json_call("", "", schema={"required": ["summary"]})
    result = finalize_resume(draft, MASTER, plan)
    assert [entry["company"] for entry in result["experience"]] == ["Acme"]
    skills = {item for group in result["skills"] for item in group["items"]}
    assert "PostgreSQL" in skills
    assert "MongoDB (transferable familiarity)" in skills

    unqualified = deepcopy(draft)
    unqualified["skills"][1]["items"][1] = "MongoDB"
    unsafe_skills = {
        item for group in finalize_resume(unqualified, MASTER, plan)["skills"]
        for item in group["items"]
    }
    assert "MongoDB" not in unsafe_skills


def test_adjacent_skill_must_be_requested_by_the_job():
    ledger = build_evidence_ledger(MASTER)
    plan = normalize_content_plan(
        _plan(), MASTER,
        {"title": "Backend Engineer", "description": "Reliable PostgreSQL services"},
        ledger,
    )
    assert not any(
        row["skill"] == "MongoDB" and row["support"] == "adjacent"
        for row in plan["selected_skills"]
    )


def test_pipeline_allows_merge_split_and_records_grounding_audit():
    provider = _EditorialProvider()
    metrics = {}
    result = run_resume_editorial_pipeline(
        MASTER,
        {
            "company": "Target", "title": "Backend Engineer",
            "description": "Reliable Python services using MongoDB",
        },
        writer_chain=[provider], verifier_chain=[provider], metrics_sink=metrics,
    )
    assert len(result["experience"]) == 1
    assert len(result["experience"][0]["bullets"]) == 2
    assert "40%" in result["experience"][0]["bullets"][0]
    assert any(
        "MongoDB" in item
        for group in result["skills"] for item in group["items"]
    )
    assert metrics["pipeline_version"] == 2
    assert metrics["audit"]["initial_grounding"]["passed"] is True
    writer_system = next(system for required, system, _ in provider.calls if "summary" in required)
    assert "merge multiple source bullets" in writer_system
    assert "split one source bullet" in writer_system


def test_pipeline_falls_back_to_selected_source_text_when_semantic_review_is_unavailable():
    metrics = {}
    result = run_resume_editorial_pipeline(
        MASTER,
        {"company": "Target", "title": "Backend Engineer", "description": "Python services"},
        writer_chain=[_EditorialProvider()],
        verifier_chain=[_UnavailableVerifier()],
        metrics_sink=metrics,
    )
    assert result["summary"] == MASTER["summary_options"][0]
    assert "semantic_grounding_source_fallback" in metrics["warnings"]
    assert metrics["audit"]["initial_grounding"]["degraded"] is True
    assert metrics["audit"]["final_grounding"]["passed"] is True
