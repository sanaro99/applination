from __future__ import annotations

from copy import deepcopy
import pytest
import re

from src.evidence import build_evidence_ledger, finalize_resume, normalize_content_plan
from src.providers.base import LLMProvider
from src.resume_pipeline import _plan_content, run_resume_editorial_pipeline


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
                        "path": "skills.2.items.0",
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
    planner_user = next(user for required, _, user in provider.calls if "role_strategy" in required)
    assert "CURATED PROJECT PREFERENCES (soft tie-breaker only)" in planner_user
    writer_system = next(system for required, system, _ in provider.calls if "summary" in required)
    assert "merge multiple source bullets" in writer_system
    assert "split one source bullet" in writer_system
    assert "Avoid repeating an award" in writer_system


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


def test_repair_verifier_outage_preserves_first_reviewed_editorial_bullets():
    class _FlakyVerifier(LLMProvider):
        name = "flaky-verifier"

        def __init__(self):
            self.calls = 0

        def text_call(self, system, user, max_tokens=1000):
            raise AssertionError

        def json_call(self, system, user, max_tokens=2000, *, schema=None):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("verifier unavailable during repair")
            paths = re.findall(r'"path": "([^"]+)"', user)
            return {"verdicts": [{
                "path": path, "claim": "needs review" if path == "summary" else "source-backed",
                "support": "unsupported" if path == "summary" else "direct",
                "evidence_ids": [] if path == "summary" else ["summary.0"],
                "action": "rewrite" if path == "summary" else "accept",
                "reason": "Unsafe summary" if path == "summary" else "Source-backed",
            } for path in paths]}

    metrics = {}
    result = run_resume_editorial_pipeline(
        MASTER, {"title": "Backend Engineer", "description": "Reliable Python services"},
        writer_chain=[_EditorialProvider()], verifier_chain=[_FlakyVerifier()],
        metrics_sink=metrics,
    )
    assert "repair_verifier_degraded_reverted" in metrics["warnings"]
    assert "semantic_grounding_source_fallback" not in metrics["warnings"]
    assert result["summary"] == MASTER["summary_options"][0]
    assert result["experience"][0]["bullets"][0].startswith("Reduced failed jobs by 40%")


def test_final_resume_preserves_source_sections_core_languages_and_chronology():
    master = deepcopy(MASTER)
    master["core_skills"] = ["Python", "SQL", "Java", "C++"]
    master["skills"]["languages"] += ["Java", "C++"]
    master["experience"] = list(reversed(master["experience"]))
    master["education"] = list(reversed(master["education"]))
    master["certifications"] = ["Azure AI Fundamentals (2024)"]
    master["awards"] = [{"name": "Engineering Award", "date": "2023"}]
    ledger = build_evidence_ledger(master)
    plan = normalize_content_plan({}, master, {"title": "Backend Engineer"}, ledger)
    draft = {
        "summary": "Backend engineer focused on reliable Python services.",
        "skills": [{"group": "Languages", "items": ["Python"]}],
        "experience": [
            {"company": row["company"], "role": row["role"], "bullets": row["bullets_all"][:1]}
            for row in master["experience"]
        ],
        "projects": [{"name": "Worker Lab", "bullets": MASTER["projects"][0]["bullets_all"]}],
    }
    result = finalize_resume(draft, master, plan)
    assert {"Python", "SQL", "Java", "C++"}.issubset({
        skill for group in result["skills"] for skill in group["items"]
    })
    assert [row["role"] for row in result["experience"]] == [
        "Software Engineer", "Support Analyst",
    ]
    assert result["certifications"] == master["certifications"]
    assert result["awards"] == master["awards"]


def test_ledger_and_output_schema_model_certifications_awards_and_project_dates():
    from src.schemas import RESUME_SCHEMA

    master = deepcopy(MASTER)
    master["projects"][0].update(start_date="Jan 2025", end_date="Present")
    master["certifications"] = ["Azure AI Fundamentals (Nov 2024)"]
    master["awards"] = [{"name": "Engineering Award", "date": "Apr 2023"}]
    ledger = build_evidence_ledger(master)
    assert any(item.kind == "certification" for item in ledger)
    assert any(item.kind == "award" for item in ledger)
    assert "Jan 2025" in next(item.text for item in ledger if item.id == "project.0")
    assert "certifications" in RESUME_SCHEMA["properties"]
    assert "awards" in RESUME_SCHEMA["properties"]


def test_planner_keeps_two_projects_when_the_model_selects_only_one():
    master = deepcopy(MASTER)
    master["projects"].append({
        "name": "Second Project", "tech": "Python", "bullets_all": ["Built another useful tool."],
    })
    ledger = build_evidence_ledger(master)
    plan = normalize_content_plan(_plan(), master, {"title": "Backend Engineer"}, ledger)
    assert len(plan["selected_projects"]) == 2


def test_fallback_planner_prefers_role_evidence_over_generic_job_vocabulary():
    master = deepcopy(MASTER)
    master["experience"][0]["bullets_all"] = [
        "Built an AI retrieval service for production diagnosis using Python and vector search.",
        "Raised engineering issues across software teams and project development work.",
        "Maintained an infrastructure monitoring service for backend teams.",
    ]
    ledger = build_evidence_ledger(master)
    plan = normalize_content_plan({}, master, {
        "title": "AI Platform Engineer",
        "description": "Software engineering teams develop project work on AI infrastructure.",
    }, ledger)
    assert plan["selected_experience"][0]["evidence_ids"][0] == "experience.0.bullet.0"


def test_fallback_project_preference_is_soft_and_source_backed():
    master = deepcopy(MASTER)
    master["projects"].append({
        "name": "Preferred Project", "tech": "Python",
        "bullets_all": ["Built a Python service for reliable delivery."],
    })
    master["preferred_projects"] = ["Preferred Project"]
    plan = normalize_content_plan({}, master, {
        "title": "Backend Engineer", "description": "Python services and reliability",
    }, build_evidence_ledger(master))
    assert plan["selected_projects"][0]["source_id"] == "project.1"


def test_planner_rejects_valid_json_with_wrong_contract():
    class _WrongShape(LLMProvider):
        name = "wrong-shape"

        def text_call(self, system, user, max_tokens=1000):
            raise AssertionError

        def json_call(self, system, user, max_tokens=2000, *, schema=None):
            return {"plan": "select the best projects"}

    with pytest.raises(RuntimeError, match="structurally invalid JSON"):
        _plan_content(MASTER, {"title": "Backend Engineer"}, build_evidence_ledger(MASTER),
                      [_WrongShape()], [])


def test_finalizer_restores_planned_older_role_instead_of_printing_duplicate_identity():
    master = deepcopy(MASTER)
    master["experience"][1] = {
        "company": "Acme", "role": "Engineering Intern", "start_date": "2021",
        "end_date": "2021", "bullets_all": ["Mapped operational workflows."],
    }
    ledger = build_evidence_ledger(master)
    plan = normalize_content_plan({}, master, {"title": "Backend Engineer"}, ledger)
    draft = {
        "summary": "Backend engineer.", "skills": [], "projects": [],
        "experience": [
            {"company": "Acme", "role": "Software Engineer", "bullets": ["Improved the queue."]},
            {"company": "Acme", "role": "Software Engineer", "bullets": ["Mapped operational workflows."]},
        ],
    }
    result = finalize_resume(draft, master, plan)
    assert [entry["role"] for entry in result["experience"]] == [
        "Software Engineer", "Engineering Intern",
    ]
    assert result["experience"][1]["bullets"] == ["Mapped operational workflows."]
