"""Intake endpoints.

The load-bearing assertion in this file is that every one of these works with
no API key configured. Capture happens before the user has a provider; if any
of this needs one, the journey is broken at its first chapter.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server.db as db

from .conftest import make_engine, register


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, "engine", engine)
    from server.app import app

    return app


@pytest.fixture()
def client(app_env):
    with TestClient(app_env) as c:
        register(c, "a@example.com")
        yield c


def test_notes_are_saved_without_any_provider_configured(client):
    r = client.post(
        "/api/onboarding/intake/notes",
        json={"text": "I built the payments migration at Stripe."},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_resume_upload_parks_text_without_any_provider_configured(client):
    r = client.post(
        "/api/onboarding/intake/resume",
        files={"file": ("cv.txt", b"Jane Doe\nSenior Backend Engineer", "text/plain")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["chars"] > 0


def test_threads_come_back_from_the_saved_notes(client):
    client.post(
        "/api/onboarding/intake/notes",
        json={"text": "I built the payments migration at Stripe, mostly python."},
    )
    r = client.get("/api/onboarding/intake/threads")
    assert r.status_code == 200, r.text
    labels = {t["label"].lower() for t in r.json()["threads"]}
    assert "stripe" in labels
    assert "python" in labels


def test_threads_on_an_empty_account_are_empty_not_an_error(client):
    r = client.get("/api/onboarding/intake/threads")
    assert r.status_code == 200
    assert r.json()["threads"] == []


def test_search_terms_are_derived_and_flagged_when_guessed(client):
    r = client.get("/api/onboarding/intake/search-terms")
    assert r.status_code == 200
    assert r.json()["guessed"] is True

    client.post(
        "/api/onboarding/intake/notes",
        json={"text": "I'm a backend engineer who writes python"},
    )
    r = client.get("/api/onboarding/intake/search-terms")
    body = r.json()
    assert body["guessed"] is False
    assert "backend engineer" in body["keywords"]


def test_draft_story_is_saved_and_does_not_count_as_a_real_story(client):
    r = client.post(
        "/api/onboarding/intake/story",
        json={"title": "The payments migration", "body": "It was messy."},
    )
    assert r.status_code == 200, r.text
    assert r.json()["slug"] == "the-payments-migration"

    status = client.get("/api/onboarding/status").json()
    assert status["steps"]["stories"] == 0
    assert status["intake"]["drafts"] == 1


def test_status_reports_the_intake_block(client):
    status = client.get("/api/onboarding/status").json()
    assert status["intake"] == {"notes": False, "resume_text": False, "drafts": 0}

    client.post("/api/onboarding/intake/notes", json={"text": "hello"})
    status = client.get("/api/onboarding/status").json()
    assert status["intake"]["notes"] is True


def test_intake_requires_a_session(app_env):
    with TestClient(app_env) as anon:
        assert anon.get("/api/onboarding/intake/threads").status_code == 401


def test_one_users_intake_is_invisible_to_another(app_env):
    with TestClient(app_env) as ca, TestClient(app_env) as cb:
        register(ca, "a@example.com")
        register(cb, "b@example.com")
        ca.post("/api/onboarding/intake/notes", json={"text": "worked at Figma"})
        threads = cb.get("/api/onboarding/intake/threads").json()["threads"]
        assert threads == []
