"""The enrichment cascade.

Capture and enrichment are separate passes because the journey runs before the
user has a key. These tests pin the two properties that make that safe: steps
are idempotent, and drafts are moved rather than deleted.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server.db as db
import src.providers as providers
from server.intake import park_resume, save_draft_story, save_notes
from server.user_paths import UserPaths

from .conftest import make_engine, register


class _FakeProvider:
    name = "fake"

    def json_call(self, system, user, max_tokens=2000, *, schema=None):
        if "keywords" in (user or "").lower() or "keywords" in (system or "").lower():
            return {"keywords": ["backend engineer", "platform engineer"]}
        return {
            "title": "A story",
            "tags": ["backend", "python"],
            "role_fit": ["swe"],
            "company_fit": ["startup"],
            "one_liner": "Did a thing that mattered.",
            "body": "Context. What I did. What mattered. Outcome.",
            "name": "Jane Doe",
            "email": "jane@example.com",
            "experience": [],
            "education": [],
            "projects": [],
            "skills": [],
        }

    def text_call(self, system, user, max_tokens=1000):
        return "I write plainly and care about shipping.\n"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, "engine", engine)
    fake = _FakeProvider()
    monkeypatch.setattr(providers, "get_provider_chain", lambda cfg: [fake])
    monkeypatch.setattr(providers, "get_provider", lambda name, cfg, **k: fake)
    monkeypatch.setattr(providers, "get_task_chains", lambda cfg: {})
    from server.app import app

    with TestClient(app) as c:
        register(c, "a@example.com")
        yield c


@pytest.fixture()
def paths():
    return UserPaths(user_id=1).ensure()


def test_plan_is_empty_when_nothing_was_captured(client):
    r = client.get("/api/onboarding/enrich/plan")
    assert r.status_code == 200, r.text
    assert r.json()["steps"] == []


def test_parked_resume_produces_a_resume_step(client, paths):
    park_resume(paths, "Jane Doe\nSenior Backend Engineer\nAcme, 2020-2024")
    ids = [s["id"] for s in client.get("/api/onboarding/enrich/plan").json()["steps"]]
    assert "resume" in ids


def test_each_draft_produces_its_own_step(client, paths):
    save_draft_story(paths, "One", "first body")
    save_draft_story(paths, "Two", "second body")
    ids = [s["id"] for s in client.get("/api/onboarding/enrich/plan").json()["steps"]]
    assert "story:one" in ids
    assert "story:two" in ids


def test_notes_produce_a_bio_step(client, paths):
    save_notes(paths, "I care about shipping things people use.")
    ids = [s["id"] for s in client.get("/api/onboarding/enrich/plan").json()["steps"]]
    assert "bio" in ids


def test_search_step_appears_once_there_is_any_material(client, paths):
    save_notes(paths, "backend work")
    ids = [s["id"] for s in client.get("/api/onboarding/enrich/plan").json()["steps"]]
    assert "search" in ids


def test_a_step_disappears_once_its_output_exists(client, paths):
    park_resume(paths, "Jane Doe\nSenior Backend Engineer")
    paths.resume_path.write_text("name: Jane Doe\n", encoding="utf-8")
    ids = [s["id"] for s in client.get("/api/onboarding/enrich/plan").json()["steps"]]
    assert "resume" not in ids


def test_every_step_names_the_ridge_it_fills(client, paths):
    park_resume(paths, "Jane Doe")
    save_draft_story(paths, "One", "body")
    for step in client.get("/api/onboarding/enrich/plan").json()["steps"]:
        assert step["part"]
        assert step["label"]


def _run(client, step_id, force=False):
    r = client.post(
        "/api/onboarding/enrich/step",
        json={"step_id": step_id, "force": force},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_resume_step_writes_resume_yaml(client, paths):
    park_resume(paths, "Jane Doe\nSenior Backend Engineer\nAcme, 2020-2024")
    out = _run(client, "resume")
    assert out["done"] is True
    assert paths.resume_path.exists()


def test_resume_step_is_idempotent(client, paths):
    park_resume(paths, "Jane Doe\nSenior Backend Engineer")
    _run(client, "resume")
    paths.resume_path.write_text("name: Untouched\n", encoding="utf-8")
    out = _run(client, "resume")
    assert out["skipped"] is True
    assert "Untouched" in paths.resume_path.read_text(encoding="utf-8")


def test_force_reruns_a_completed_step(client, paths):
    park_resume(paths, "Jane Doe\nSenior Backend Engineer")
    _run(client, "resume")
    paths.resume_path.write_text("name: Untouched\n", encoding="utf-8")
    out = _run(client, "resume", force=True)
    assert out["skipped"] is False
    assert "Untouched" not in paths.resume_path.read_text(encoding="utf-8")


def test_story_step_writes_a_real_story(client, paths):
    save_draft_story(paths, "One", "we shipped it on a Friday")
    out = _run(client, "story:one")
    assert out["done"] is True
    real = [p for p in paths.stories_dir.glob("*.md") if not p.name.startswith("_")]
    assert len(real) == 1


def test_story_step_moves_the_draft_to_consumed_rather_than_deleting_it(client, paths):
    save_draft_story(paths, "One", "we shipped it on a Friday")
    _run(client, "story:one")
    assert list(paths.intake_stories_dir.glob("*.md")) == []
    consumed = list(paths.intake_consumed_dir.glob("*.md"))
    assert len(consumed) == 1
    assert "we shipped it on a Friday" in consumed[0].read_text(encoding="utf-8")


def test_bio_step_writes_bio_md(client, paths):
    save_notes(paths, "I care about shipping things people use.")
    out = _run(client, "bio")
    assert out["done"] is True
    assert paths.bio_path.exists()


def test_search_step_proposes_without_writing_config(client, paths):
    save_notes(paths, "backend work in python")
    before = client.get("/api/config").json()["text"]
    out = _run(client, "search")
    assert out["result"]["keywords"]
    after = client.get("/api/config").json()["text"]
    assert before == after


def test_an_unknown_step_id_is_a_400(client):
    r = client.post(
        "/api/onboarding/enrich/step", json={"step_id": "nonsense", "force": False}
    )
    assert r.status_code == 400


def test_a_missing_draft_is_a_404(client):
    r = client.post(
        "/api/onboarding/enrich/step", json={"step_id": "story:ghost", "force": False}
    )
    assert r.status_code == 404
