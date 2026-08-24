"""Chapter 5's payoff: real job inventory, zero tokens.

fetch_all() is pure HTTP, so this whole feature works before the user has an
API key. The tests fake it — the point is the caching, the degradation and the
counting, not the network.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server.db as db
import server.job_preview as job_preview

from .conftest import make_engine, register


class _Job:
    def __init__(self, title, company="Acme", description=""):
        self.title = title
        self.company = company
        self.description = description
        self.url = "https://example.com/j"
        self.location = "Remote"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, "engine", engine)
    job_preview.reset()
    from server.app import app

    with TestClient(app) as c:
        register(c, "a@example.com")
        yield c


def test_status_before_anything_started_is_idle(client):
    r = client.get("/api/onboarding/preview-jobs")
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "idle"


def test_a_preview_runs_and_counts_matches(client, monkeypatch):
    monkeypatch.setattr(
        job_preview,
        "_fetch",
        lambda cfg: (
            [_Job("Backend Engineer"), _Job("Chef"), _Job("Python Developer")],
            9,
            9,
        ),
    )
    client.post(
        "/api/onboarding/intake/notes",
        json={"text": "I'm a backend engineer who writes python"},
    )
    assert client.post("/api/onboarding/preview-jobs").status_code == 200
    body = client.get("/api/onboarding/preview-jobs").json()
    assert body["state"] == "ready"
    assert body["total"] == 3
    assert body["matched"] == 2
    assert len(body["sample"]) == 2


def test_partial_source_failure_is_reported_not_fatal(client, monkeypatch):
    monkeypatch.setattr(
        job_preview, "_fetch", lambda cfg: ([_Job("Backend Engineer")], 6, 9)
    )
    client.post("/api/onboarding/preview-jobs")
    body = client.get("/api/onboarding/preview-jobs").json()
    assert body["state"] == "ready"
    assert body["sources_ok"] == 6
    assert body["sources_total"] == 9


def test_a_failing_fetch_becomes_an_error_state_not_a_500(client, monkeypatch):
    def boom(cfg):
        raise RuntimeError("network down")

    monkeypatch.setattr(job_preview, "_fetch", boom)
    client.post("/api/onboarding/preview-jobs")
    body = client.get("/api/onboarding/preview-jobs").json()
    assert body["state"] == "error"
    assert "network down" in body["error"]


def test_results_are_cached_per_user(client, monkeypatch):
    calls = []

    def counting(cfg):
        calls.append(1)
        return ([_Job("Backend Engineer")], 9, 9)

    monkeypatch.setattr(job_preview, "_fetch", counting)
    client.post("/api/onboarding/preview-jobs")
    client.post("/api/onboarding/preview-jobs")
    assert len(calls) == 1


def test_preview_requires_a_session(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, "engine", engine)
    from server.app import app

    with TestClient(app) as anon:
        assert anon.get("/api/onboarding/preview-jobs").status_code == 401


# --- The keywords the count is actually about --------------------------------
#
# Chapter 5 claims these postings "look like you". That is only true if the
# keywords came from the user. A fresh config.yaml carries the committed
# template's example keywords, which came from nobody.


def test_seeded_template_keywords_do_not_drive_the_count(client, monkeypatch):
    """The example config asks for intern roles. The user said neither word."""
    monkeypatch.setattr(
        job_preview,
        "_fetch",
        lambda cfg: ([_Job("Software Engineer Intern"), _Job("Backend Engineer")], 9, 9),
    )
    client.post(
        "/api/onboarding/intake/notes",
        json={"text": "I'm a backend engineer who writes python"},
    )
    client.post("/api/onboarding/preview-jobs")
    body = client.get("/api/onboarding/preview-jobs").json()
    assert body["matched"] == 1
    assert body["sample"][0]["title"] == "Backend Engineer"


def test_the_users_own_keywords_do_drive_the_count(client, monkeypatch):
    monkeypatch.setattr(
        job_preview,
        "_fetch",
        lambda cfg: ([_Job("Data Scientist"), _Job("Backend Engineer")], 9, 9),
    )
    r = client.put("/api/onboarding/search", json={"keywords": ["data scientist"]})
    assert r.status_code == 200, r.text
    client.post("/api/onboarding/preview-jobs")
    body = client.get("/api/onboarding/preview-jobs").json()
    assert body["matched"] == 1
    assert body["sample"][0]["title"] == "Data Scientist"
