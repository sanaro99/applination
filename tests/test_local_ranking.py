"""Local ranking must work through the real pipeline without an LLM."""
from __future__ import annotations

import logging

import pytest

from src.main import rank_and_filter
from src.scrapers import Job


MASTER = {
    "summary_options": ["Backend software engineer building reliable APIs."],
    "core_skills": ["Python", "SQL"],
    "skills": {"languages": ["Python", "SQL"], "tools": ["Docker"]},
    "projects": [{"name": "API service", "tech": "Python, SQL, Docker"}],
}
CFG = {
    "llm": {"tasks": {"ranking": {"method": "bm25"}}},
    "search": {
        "keywords": ["software engineer"],
        "min_match_score": 55,
        "max_jobs_per_day": 200,
    },
}


class NoLlm:
    def rank_jobs(self, jobs, profile):
        pytest.fail("Local ranking called the LLM ranker")


def job(title="Software Engineer", description="Python SQL Docker backend APIs", company="Acme"):
    return Job(source="test", company=company, title=title, description=description,
               location="Remote", url=f"https://example.com/{company}")


def test_local_ranking_scores_200_jobs_without_calling_a_provider():
    jobs = [job(company=f"Company {i}") for i in range(200)]
    selected = rank_and_filter(
        jobs, CFG, NoLlm(), "Python SQL Docker backend software engineer APIs",
        logging.getLogger("test"),
    )
    assert len(selected) == 200
    assert all(55 <= j.match_score <= 100 and j.match_reason for j in jobs)


def test_local_ranking_preserves_seniority_and_duplicate_guards():
    jobs = [job(), job(title="Senior Software Engineer", company="Senior"),
            job(company="Already applied"), job(title="Florist", description="Flowers bouquets")]
    selected = rank_and_filter(
        jobs, CFG, NoLlm(), "Python SQL Docker backend software engineer APIs",
        logging.getLogger("test"), candidate_profile={"seniority": "student"},
        excluded_keys={jobs[2].dedupe_key()},
    )
    assert selected == [jobs[0]]
    assert jobs[1].match_score == 0
    assert jobs[2]._excluded is True
    assert jobs[3].match_score == 0


def test_default_ranking_still_uses_the_existing_llm_path():
    from src.tailor import Tailor
    from src.providers.demo_provider import DemoProvider

    selected = rank_and_filter(
        [job()], {"search": {"min_match_score": 0, "max_jobs_per_day": 1}},
        Tailor(task_chains={"ranking": [DemoProvider()]}), "Python",
        logging.getLogger("test"),
    )
    assert len(selected) == 1
    assert 0 <= selected[0].match_score <= 100


def test_local_ranking_uses_skills_beyond_the_short_profile_blurb():
    jobs = [job(description="Distributed systems using Kafka", title="Data Engineer"),
            job(description="Design flowers and bouquets", title="Florist")]
    selected = rank_and_filter(
        jobs, {**CFG, "search": {**CFG["search"], "min_match_score": 1}},
        NoLlm(), "unrelated short summary", logging.getLogger("test"),
        master_resume={"skills": {"tools": ["Kafka"]}},
    )
    assert selected == [jobs[0]]
    assert "kafka" in jobs[0].match_reason.lower()


def test_local_ranking_reads_the_full_job_description():
    from src.ranking import rank_jobs

    scores = rank_jobs(
        [{"title": "", "desc": "About our company. " * 30 + "Python SQL Docker"},
         {"title": "", "desc": "About our company. " * 30 + "Flowers bouquets"}],
        "Python SQL Docker",
    )
    assert scores[0]["score"] > scores[1]["score"] == 0
    assert "python" in scores[0]["reason"].lower()


def test_local_ranking_boosts_a_matching_role_title():
    from src.ranking import rank_jobs

    scores = rank_jobs(
        [{"title": "Software Engineer", "desc": "Python SQL"},
         {"title": "Instructor", "desc": "Python SQL"}],
        "Python SQL", keywords=["software engineer"],
    )
    assert scores[0]["score"] > scores[1]["score"]


@pytest.mark.parametrize("skill,unrelated", [("C++", "C"), ("C#", "C++"), ("Java", "JavaScript")])
def test_local_ranking_keeps_distinct_programming_languages_separate(skill, unrelated):
    from src.ranking import rank_jobs

    scores = rank_jobs([{"desc": skill}, {"desc": unrelated}], skill)
    assert scores[0]["score"] > 0
    assert scores[1]["score"] == 0


def test_local_ranking_recognizes_common_technology_spellings():
    from src.ranking import rank_jobs

    scores = rank_jobs([{"desc": "Postgres k8s golang"}], "PostgreSQL Kubernetes Go")
    assert scores[0]["score"] >= 55


def test_local_ranking_cannot_make_a_weak_only_match_perfect():
    from src.ranking import rank_jobs

    scores = rank_jobs([{"desc": "Python " * 100}], "Python SQL Docker Kafka Kubernetes")
    assert 0 < scores[0]["score"] < 55


def test_local_ranking_handles_empty_input_and_empty_vocabulary():
    from src.ranking import rank_jobs

    assert rank_jobs([], "Python") == []
    scores = rank_jobs([{}, {"title": "Engineer", "desc": "the and a"}], "")
    assert [s["idx"] for s in scores] == [0, 1]
    assert [s["score"] for s in scores] == [0, 0]


@pytest.mark.parametrize("count", [1, 25, 200])
def test_repeating_matching_postings_does_not_make_them_fail_the_threshold(count):
    from src.ranking import rank_jobs

    scores = rank_jobs(
        [{"title": "Software Engineer", "desc": "Python SQL Docker"}] * count,
        "", master_resume={"core_skills": ["Python", "SQL", "Docker"],
                           "summary_options": ["Built reliable APIs."]},
        keywords=["software engineer"],
    )
    assert all(s["score"] >= 55 for s in scores)


def test_long_resume_narrative_does_not_drown_out_actual_matching_skills():
    from src.ranking import rank_jobs

    scores = rank_jobs(
        [{"title": "Software Engineer", "desc": "Python SQL Docker"}] * 200,
        "", master_resume={"core_skills": ["Python", "SQL", "Docker"],
                           "summary_options": [" ".join(f"achievement{i}" for i in range(200))]},
        keywords=["software engineer"],
    )
    assert scores[0]["score"] >= 55


def test_html_entities_in_programming_languages_are_decoded():
    from src.ranking import rank_jobs

    scores = rank_jobs([{"desc": "<p>C&#43;&#43; C&#35; &amp; .NET</p>"},
                        {"desc": "<p>C++ C# & .NET</p>"}], "C++ C# .NET")
    assert scores[0]["score"] == scores[1]["score"] > 0


@pytest.mark.parametrize("count", [25, 200])
def test_sparse_postings_do_not_suppress_a_complete_matching_job(count):
    from src.ranking import rank_jobs

    scores = rank_jobs(
        [{"title": "Software Engineer", "desc": "Python SQL Docker"}] +
        [{"title": "Intern", "desc": ""}] * (count - 1),
        "", master_resume={"core_skills": ["Python", "SQL", "Docker"],
                           "summary_options": ["Built reliable APIs."]},
        keywords=["software engineer"],
    )
    assert scores[0]["score"] >= 55
    assert all(s["score"] == 0 for s in scores[1:])


def test_local_dry_run_does_not_need_any_llm_keys(tmp_path, monkeypatch):
    from server.user_paths import UserPaths
    from src import pipeline

    paths = UserPaths(user_id=1).ensure()
    import yaml
    paths.resume_path.write_text(yaml.safe_dump(MASTER), encoding="utf-8")
    monkeypatch.setattr(pipeline, "fetch_all", lambda cfg, log: [job()])
    cfg = {**CFG, "user": {"full_name": "Test User"}, "output": {"produce_pdf": False}}
    events = []
    result = pipeline.run_pipeline(cfg, paths=paths, dry_run=True, on_event=events.append)
    assert result["jobs_found"] == 1
    assert result["dry_run"] is True
    pool = next(e for e in events if e["type"] == "rank_pool")
    assert len(pool["jobs"]) == 1
    assert pool["jobs"][0]["selected"] is True


def test_local_mode_does_not_construct_a_ranking_provider():
    from src.providers.factory import get_task_chains

    chains = get_task_chains({"primary": "demo", "tasks": {
        "ranking": {"method": "bm25", "primary": "does-not-exist"},
    }})
    assert "ranking" not in chains
    assert "tailoring" in chains


def test_invalid_yaml_ranking_method_is_not_silently_treated_as_llm():
    cfg = {**CFG, "llm": {"tasks": {"ranking": {"method": "typo"}}}}
    with pytest.raises(ValueError, match="ranking method"):
        rank_and_filter([job()], cfg, NoLlm(), "Python", logging.getLogger("test"))
