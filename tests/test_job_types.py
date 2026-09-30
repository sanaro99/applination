"""Explicit target types must reach requests and govern returned jobs."""
import logging
from datetime import datetime, timezone

import pytest

from src import main
from src.scrapers import Job, jsearch, lever, adzuna, himalayas, themuse
from src.target_rules import allows_job, role_keywords, target_kind
from .test_target_rules import Response, job


@pytest.mark.parametrize("kind,title,allowed", [
    ("full_time", "Software Engineer Intern", False),
    ("full_time", "Software Engineer Co-op", False),
    ("full_time", "Software Engineer (Contract)", False),
    ("full_time", "Software Engineer", True),
    ("internship", "Software Engineer Intern", True),
    ("internship", "Software Engineer Co-op", False),
    ("co_op", "Software Engineer Co-op", True),
    ("co_op", "Software Engineer Intern", False),
    ("contract", "Software Engineer (Contract)", True),
    ("contract", "Software Engineer", False),
    ("temporary", "Temporary Software Engineer", True),
    ("temporary", "Software Engineer", False),
    ("part_time", "Part-time Software Engineer", True),
    ("part_time", "Software Engineer", False),
    ("any", "Software Engineer Intern", True),
])
def test_explicit_type_overrides_keywords(kind, title, allowed):
    assert allows_job(job(title), {"keywords": ["software engineer intern"],
                                   "job_type": kind}) is allowed


def test_metadata_identifies_type_without_title_hint():
    posting = job("Software Engineer")
    posting.employment_type = "Temporary"
    assert allows_job(posting, {"job_type": "temporary"})
    assert not allows_job(posting, {"job_type": "full_time"})


def test_description_requires_a_type_declaration():
    posting = job("Software Engineer")
    posting.description = "Prior internship experience is welcome. We use temporary credentials."
    assert allows_job(posting, {"job_type": "full_time"})
    assert not allows_job(posting, {"job_type": "temporary"})
    posting.description = "This is a temporary position for six months."
    assert allows_job(posting, {"job_type": "temporary"})


def test_contract_management_is_a_role_not_an_employment_type():
    assert role_keywords({"job_type": "full_time", "keywords": ["Contract Manager"]}) == ["Contract Manager"]
    assert target_kind(["contract manager"]) == "any"
    posting = job("Contract Manager")
    posting.employment_type = "Full Time"
    posting.description = "This role is a Contract Manager position."
    assert allows_job(posting, {"job_type": "full_time"})
    assert not allows_job(posting, {"job_type": "contract"})


def test_full_time_hours_do_not_override_a_contract_declaration():
    posting = job("Software Engineer")
    posting.employment_type = "Full Time"
    posting.description = "This is a contract position for six months."
    assert allows_job(posting, {"job_type": "contract"})
    assert not allows_job(posting, {"job_type": "full_time"})


@pytest.mark.parametrize("description", [
    "This role is ideal for candidates with prior internship experience.",
    "This position is responsible for contract negotiations.",
    "This role is a full-time position requiring previous internship experience.",
])
def test_description_classifies_only_direct_employment_declarations(description):
    posting = job("Software Engineer")
    posting.description = description
    assert allows_job(posting, {"job_type": "full_time"})
    assert not allows_job(posting, {"job_type": "internship"})
    assert not allows_job(posting, {"job_type": "contract"})


def test_volunteer_metadata_is_not_missing_full_time_metadata():
    posting = job("Software Engineer")
    posting.employment_type = "Volunteer"
    assert not allows_job(posting, {"job_type": "full_time"})
    assert allows_job(posting, {"job_type": "any"})


@pytest.mark.parametrize("description,kind", [
    ("This is a full-time contract position for six months.", "contract"),
    ("This role is a full-time temporary position.", "temporary"),
    ("Job type: Full-time, prior internship experience is welcome.", "full_time"),
    ("Employment: Part-time", "part_time"),
])
def test_type_declarations_capture_employment_qualifiers_only(description, kind):
    posting = job("Software Engineer")
    posting.description = description
    assert allows_job(posting, {"job_type": kind})
    if kind != "full_time":
        assert not allows_job(posting, {"job_type": "full_time"})


def test_selected_type_reaches_fetch_and_rank(monkeypatch):
    captured = {}

    def fetch(keywords, **kwargs):
        captured.update(keywords=keywords, **kwargs)
        return [job("Software Engineer"), job("Software Engineer Intern")]

    monkeypatch.setattr(main.jsearch, "fetch", fetch)
    sources = {key: {"enabled": key == "jsearch"}
               for key in ("remotive", "themuse", "greenhouse", "adzuna",
                           "jsearch", "simplify_github", "lever")}
    sources["jsearch"]["rapidapi_key"] = "test"
    cfg = {"sources": sources, "search": {
        "job_type": "full_time", "keywords": ["software engineer intern"],
        "last_n_hours": 24, "min_match_score": 55, "max_jobs_per_day": 5,
    }}
    found = main.fetch_all(cfg, logging.getLogger(__name__))
    assert captured["job_type"] == "full_time"
    assert captured["keywords"] == ["software engineer"]
    assert [j.title for j in found] == ["Software Engineer"]

    class Ranker:
        def rank_jobs(self, jobs, profile):
            captured["profile"] = profile
            return [{"idx": i, "score": 90} for i in range(len(jobs))]

    selected = main.rank_and_filter(found, cfg, Ranker(), "candidate", logging.getLogger(__name__))
    assert len(selected) == 1
    assert "Job type: full_time" in captured["profile"]


@pytest.mark.parametrize("kind,wire", [
    ("full_time", "FULLTIME"), ("part_time", "PARTTIME"),
    ("internship", "INTERN"), ("contract", "CONTRACTOR"),
    ("co_op", None), ("temporary", None), ("any", None),
])
def test_jsearch_translates_job_type(monkeypatch, kind, wire):
    captured = []
    monkeypatch.setattr(jsearch.requests, "get", lambda *a, **kw:
                        captured.append(kw["params"]) or Response({"data": []}))
    jsearch.fetch(["software engineer"], "test", ["us"], job_type=kind)
    assert captured[0].get("employment_types") == wire
    if kind in {"co_op", "temporary"}:
        assert ("co-op" if kind == "co_op" else "temporary") in captured[0]["query"]


@pytest.mark.parametrize("kind,wire", [
    ("full_time", "Full Time"), ("part_time", "Part Time"),
    ("internship", "Intern"), ("contract", "Contractor"),
    ("temporary", "Temporary"), ("co_op", None), ("any", None),
])
def test_himalayas_translates_job_type(monkeypatch, kind, wire):
    captured = []
    monkeypatch.setattr(himalayas.requests, "get", lambda *a, **kw:
                        captured.append(kw["params"]) or Response({"jobs": []}))
    himalayas.fetch(["engineer"], job_type=kind)
    assert captured[0].get("employment_type") == wire


@pytest.mark.parametrize("kind,flag", [
    ("full_time", "full_time"), ("part_time", "part_time"), ("contract", "contract"),
])
def test_adzuna_translates_job_type(monkeypatch, kind, flag):
    captured = []
    monkeypatch.setattr(adzuna.requests, "get", lambda *a, **kw:
                        captured.append(kw["params"]) or Response({"results": []}))
    adzuna.fetch(["engineer"], "id", "key", job_type=kind)
    assert captured[0][flag] == "1"


def test_muse_internship_level_is_only_requested_for_internship(monkeypatch):
    captured = []
    monkeypatch.setattr(themuse.requests, "get", lambda *a, **kw:
                        captured.append(kw["params"]) or Response({"results": []}))
    themuse.fetch(["engineer"], job_type="internship")
    themuse.fetch(["engineer"], job_type="full_time")
    assert captured[0]["level"] == "Internship"
    assert "level" not in captured[1]


def test_lever_retains_commitment_for_common_filter(monkeypatch):
    monkeypatch.setattr(lever.requests, "get", lambda *a, **kw: Response([{
        "text": "Software Engineer", "categories": {"commitment": "Contract"},
    }]))
    found = lever.fetch(["acme"], ["engineer"])
    assert allows_job(found[0], {"job_type": "contract"})
    assert not allows_job(found[0], {"job_type": "full_time"})


def test_himalayas_preserves_typed_posting_with_current_location_payload(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(himalayas.requests, "get", lambda *a, **kw: Response({"jobs": [{
        "title": "Software Engineer", "companyName": "Acme", "employmentType": "Temporary",
        "locationRestrictions": [{"name": "United States", "alpha2": "US"}],
        "pubDate": int(now.timestamp() * 1000),
    }]}))
    found = himalayas.fetch(["engineer"], job_type="temporary", max_pages=1)
    assert len(found) == 1 and found[0].location == "United States"
    assert found[0].posted_at is not None
    assert allows_job(found[0], {"job_type": "temporary"})
