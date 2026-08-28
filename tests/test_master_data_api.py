"""The master-data endpoints, at their own door.

Every path here is per-user through ``paths_for``; there is no DB query and so
no scoping marker. The tests that matter are that the URLs did not move, that
one account cannot read another's file, and that the structured and text views
of the same file agree.
"""
from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient

import server.db as db
from server.user_paths import UserPaths

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


def test_the_router_is_registered_and_the_text_urls_did_not_move(client):
    assert client.get("/api/master-data/resume").status_code == 200
    assert client.get("/api/master-data/bio").status_code == 200
    assert client.get("/api/master-data/stories").status_code == 200


def test_the_text_put_still_writes(client):
    r = client.put(
        "/api/master-data/resume", json={"text": "core_skills:\n  - Python\n"}
    )
    assert r.status_code == 200, r.text
    on_disk = UserPaths(user_id=1).resume_path.read_text(encoding="utf-8")
    assert yaml.safe_load(on_disk)["core_skills"] == ["Python"]


def test_the_text_put_still_rejects_broken_yaml(client):
    r = client.put("/api/master-data/resume", json={"text": "a:\n  - b\n - c\n"})
    assert r.status_code == 400


def test_master_data_requires_a_session(app_env):
    with TestClient(app_env) as anon:
        assert anon.get("/api/master-data/resume").status_code == 401


def test_structured_get_returns_the_parsed_document(client):
    client.put(
        "/api/master-data/resume",
        json={"text": "core_skills:\n  - Python\nsummary_options:\n  - Engineer\n"},
    )
    r = client.get("/api/master-data/resume/structured")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["core_skills"] == ["Python"]


def test_structured_get_normalizes_the_old_skills_list(client):
    """Guards PR #57: a file written before the shape was settled must still
    load, not crash the form."""
    client.put(
        "/api/master-data/resume",
        json={"text": "skills:\n  - group: languages\n    items:\n      - Python\n"},
    )
    r = client.get("/api/master-data/resume/structured")
    assert r.json()["data"]["skills"] == {"languages": ["Python"]}


def test_structured_get_on_an_account_with_no_resume_is_empty_not_404(client):
    r = client.get("/api/master-data/resume/structured")
    assert r.status_code == 200
    assert r.json()["data"] == {}


def test_structured_get_requires_a_session(app_env):
    with TestClient(app_env) as anon:
        r = anon.get("/api/master-data/resume/structured")
        assert r.status_code == 401


VALID = {
    "summary_options": ["Engineer"],
    "core_skills": ["Python"],
    "skills": {"languages": ["Python"]},
    "experience": [
        {"company": "X", "role": "Software Engineer", "bullets_all": ["Shipped a thing."]}
    ],
    "education": [{"school": "U", "degree": "BS CS"}],
}


def test_structured_put_writes_the_file(client):
    r = client.put("/api/master-data/resume/structured", json={"data": VALID})
    assert r.status_code == 200, r.text
    on_disk = yaml.safe_load(
        UserPaths(user_id=1).resume_path.read_text(encoding="utf-8")
    )
    assert on_disk["core_skills"] == ["Python"]
    assert on_disk["skills"] == {"languages": ["Python"]}


def test_a_no_op_save_neither_reorders_nor_drops_keys(client):
    client.put("/api/master-data/resume/structured", json={"data": VALID})
    first = client.get("/api/master-data/resume/structured").json()["data"]
    client.put("/api/master-data/resume/structured", json={"data": first})
    second = client.get("/api/master-data/resume/structured").json()["data"]
    assert second == first
    assert list(second) == list(first)


def test_structured_put_preserves_a_comment_added_through_the_text_editor(client):
    client.put(
        "/api/master-data/resume",
        json={"text": "# hands off\ncore_skills:\n  - Python\nprivate: yes\n"},
    )
    client.put("/api/master-data/resume/structured", json={"data": VALID})
    on_disk = UserPaths(user_id=1).resume_path.read_text(encoding="utf-8")
    assert "# hands off" in on_disk
    assert yaml.safe_load(on_disk)["private"] is True


def test_a_missing_required_field_is_rejected_by_name(client):
    broken = {
        **VALID,
        "experience": [{"role": "Software Engineer", "bullets_all": ["x"]}],
    }
    r = client.put("/api/master-data/resume/structured", json={"data": broken})
    assert r.status_code == 400
    assert "experience[0]" in r.json()["detail"]
    assert "company" in r.json()["detail"]


def test_a_wrong_type_is_rejected_by_path(client):
    broken = {**VALID, "core_skills": "Python"}
    r = client.put("/api/master-data/resume/structured", json={"data": broken})
    assert r.status_code == 400
    assert "core_skills" in r.json()["detail"]


def test_a_rejected_save_does_not_touch_the_file(client):
    client.put("/api/master-data/resume", json={"text": "core_skills:\n  - Original\n"})
    client.put(
        "/api/master-data/resume/structured",
        json={"data": {**VALID, "core_skills": "not a list"}},
    )
    on_disk = yaml.safe_load(
        UserPaths(user_id=1).resume_path.read_text(encoding="utf-8")
    )
    assert on_disk["core_skills"] == ["Original"]


def test_structured_and_text_views_agree_on_the_same_file(client):
    client.put("/api/master-data/resume/structured", json={"data": VALID})
    text = client.get("/api/master-data/resume").json()["text"]
    structured = client.get("/api/master-data/resume/structured").json()["data"]
    assert yaml.safe_load(text)["core_skills"] == structured["core_skills"]


def test_structured_put_requires_a_session(app_env):
    with TestClient(app_env) as anon:
        r = anon.put("/api/master-data/resume/structured", json={"data": VALID})
        assert r.status_code == 401


def test_mapping_shaped_skills_are_accepted_even_though_the_schema_wants_a_list(client):
    """The schema and the disk format disagree about `skills` on purpose. If
    this fails, someone has "fixed" one of the two shapes and broken the other."""
    r = client.put(
        "/api/master-data/resume/structured",
        json={"data": {**VALID, "skills": {"languages": ["Python"], "data": ["SQL"]}}},
    )
    assert r.status_code == 200, r.text
    on_disk = yaml.safe_load(
        UserPaths(user_id=1).resume_path.read_text(encoding="utf-8")
    )
    assert on_disk["skills"] == {"languages": ["Python"], "data": ["SQL"]}
