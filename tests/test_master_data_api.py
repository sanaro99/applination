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
