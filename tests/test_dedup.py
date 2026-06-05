"""Cross-run de-duplication: shared key + rank_and_filter exclusion.

Pure-Python; the ranker is stubbed so no LLM is called.
"""
from __future__ import annotations
import logging

from src import main
from src.scrapers import Job, dedupe_key

log = logging.getLogger("test")
log.addHandler(logging.NullHandler())


class _StubTailor:
    """Scores jobs by position so ordering is deterministic without an LLM."""

    def rank_jobs(self, mini, profile):
        return [{"idx": i, "score": 90 - i, "reason": "r"} for i in range(len(mini))]


def _jobs():
    return [
        Job(source="s", company="Acme", title="SWE Intern", location="NYC", url="u1", description="d"),
        Job(source="s", company="Globex", title="ML Intern", location="SF", url="u2", description="d"),
        Job(source="s", company="Initech", title="Data Intern", location="LA", url="u3", description="d"),
    ]


_CFG = {"search": {"min_match_score": 10, "max_jobs_per_day": 50}}


def test_dedupe_key_is_case_and_whitespace_insensitive():
    assert dedupe_key("Acme Corp", "SWE Intern") == dedupe_key("  acme corp ", "swe intern  ")
    assert dedupe_key("Acme", "SWE") != dedupe_key("Acme", "MLE")


def test_dedupe_key_matches_job_method():
    j = Job(source="s", company="Acme", title="SWE", location="", url="", description="")
    assert j.dedupe_key() == dedupe_key("Acme", "SWE")


def test_excluded_job_is_dropped_from_selection():
    jobs = _jobs()
    excluded = {dedupe_key("Globex", "ML Intern")}
    top = main.rank_and_filter(jobs, _CFG, _StubTailor(), "p", log,
                               candidate_profile={}, excluded_keys=excluded)
    companies = [j.company for j in top]
    assert "Globex" not in companies
    assert companies == ["Acme", "Initech"]
    # The excluded job carries the marker so pipeline.py drops it from the pool too.
    globex = next(j for j in jobs if j.company == "Globex")
    assert getattr(globex, "_excluded", False) is True


def test_no_exclusions_keeps_everything_and_is_idempotent():
    jobs = _jobs()
    # Run once with an exclusion, then again with none on the SAME objects:
    # the marker must reset so nothing leaks between calls.
    main.rank_and_filter(jobs, _CFG, _StubTailor(), "p", log, candidate_profile={},
                         excluded_keys={dedupe_key("Globex", "ML Intern")})
    top = main.rank_and_filter(jobs, _CFG, _StubTailor(), "p", log, candidate_profile={})
    assert [j.company for j in top] == ["Acme", "Globex", "Initech"]
