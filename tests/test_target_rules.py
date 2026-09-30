"""Saved search rules must govern the jobs a run can fetch and select."""
import logging

from src import main
from src.scrapers import Job
from src.scrapers import greenhouse, jsearch, lever, remotive, themuse
from src.target_rules import allows_job, target_kind


def job(title, *, location="Seattle, WA", remote=False):
    return Job(source="test", company="Acme", title=title, location=location,
               url=title, description="Software engineering", remote=remote)


def test_full_time_run_does_not_fetch_or_select_internships(monkeypatch):
    calls = []
    monkeypatch.setattr(main.themuse, "fetch", lambda *a, **kw: [
        job("Software Engineer Intern"), job("New Grad Software Engineer")
    ])
    monkeypatch.setattr(main.simplify_github, "fetch", lambda *a, **kw: calls.append("simplify") or [job("Intern")])
    cfg = {
        "search": {"keywords": ["software engineer new grad", "full-time"],
                   "last_n_hours": 72, "countries": ["us"], "remote_ok": True,
                   "onsite_cities": ["Seattle"]},
        "sources": {key: {"enabled": key in {"themuse", "simplify_github"}}
                    for key in ("remotive", "themuse", "greenhouse", "adzuna",
                                "jsearch", "simplify_github", "lever")},
    }

    found = main.fetch_all(cfg, logging.getLogger(__name__))

    assert [j.title for j in found] == ["New Grad Software Engineer"]
    assert calls == []


def test_location_rules_keep_remote_and_chosen_onsite_city(monkeypatch):
    monkeypatch.setattr(main.themuse, "fetch", lambda *a, **kw: [
        job("Backend Engineer", location="Remote", remote=True),
        job("Data Engineer", location="Seattle, WA"),
        job("ML Engineer", location="Boston, MA"),
    ])
    cfg = {"search": {"keywords": ["engineer"], "last_n_hours": 72,
                      "remote_ok": False, "onsite_cities": ["Seattle"]},
           "sources": {key: {"enabled": key == "themuse"}
                       for key in ("remotive", "themuse", "greenhouse", "adzuna",
                                   "jsearch", "simplify_github", "lever")}}

    found = main.fetch_all(cfg, logging.getLogger(__name__))

    assert [j.title for j in found] == ["Data Engineer"]


def test_job_type_rules_keep_intern_and_mixed_searches_intentional():
    internship = job("Software Engineer Intern")
    full_time = job("New Grad Software Engineer")

    assert target_kind(["software engineer intern"]) == "internship"
    assert allows_job(internship, {"keywords": ["software engineer intern"]})
    assert not allows_job(full_time, {"keywords": ["software engineer intern"]})
    assert target_kind(["software engineer intern", "new grad software engineer"]) == "any"
    assert allows_job(internship, {"keywords": ["software engineer intern", "new grad"]})
    assert allows_job(full_time, {"keywords": ["software engineer intern", "new grad"]})


class Response:
    status_code = 200

    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


def test_jsearch_queries_saved_keywords_without_internship_constraint(monkeypatch):
    params = []

    def get(*a, **kw):
        params.append(kw["params"])
        return Response({"data": [{"job_title": "New Grad Software Engineer",
                                   "employer_name": "Acme"}]})

    monkeypatch.setattr(jsearch.requests, "get", get)
    monkeypatch.setattr(jsearch.time, "sleep", lambda *_: None)
    found = jsearch.fetch(["software engineer new grad"], "rapid-key", ["us"])

    assert found and found[0].title == "New Grad Software Engineer"
    assert all("software engineer new grad" in p["query"] for p in params)
    assert all(p.get("employment_types") != "INTERN" for p in params)


def test_muse_does_not_request_internship_level_for_new_grads(monkeypatch):
    params = []

    def get(*a, **kw):
        params.append(kw["params"])
        return Response({"results": [{"name": "New Grad Software Engineer",
                                     "company": {"name": "Acme"}}]})

    monkeypatch.setattr(themuse.requests, "get", get)
    found = themuse.fetch(["software engineer new grad"], max_pages=1)

    assert found and found[0].title == "New Grad Software Engineer"
    assert all(p.get("level") != "Internship" for p in params)


def test_lever_keeps_matching_full_time_posting(monkeypatch):
    monkeypatch.setattr(lever.requests, "get", lambda *a, **kw: Response([{
        "text": "New Grad Software Engineer", "commitment": "Full-time",
        "descriptionPlain": "New grad software engineering", "hostedUrl": "https://example.com/job",
    }]))
    found = lever.fetch(["acme"], ["new grad"])

    assert [j.title for j in found] == ["New Grad Software Engineer"]


def test_greenhouse_does_not_admit_unmatched_intern_posting(monkeypatch):
    monkeypatch.setattr(greenhouse.requests, "get", lambda *a, **kw: Response({
        "jobs": [{"title": "Marketing Intern"}, {"title": "New Grad Software Engineer"}]
    }))
    found = greenhouse.fetch(["acme"], ["new grad"], use_builtin_list=False)

    assert [j.title for j in found] == ["New Grad Software Engineer"]


def test_remotive_keeps_non_intern_posting(monkeypatch):
    monkeypatch.setattr(remotive.requests, "get", lambda *a, **kw: Response({
        "jobs": [{"title": "New Grad Software Engineer", "company_name": "Acme"}]
    }))
    found = remotive.fetch(["new grad"])

    assert [j.title for j in found] == ["New Grad Software Engineer"]
