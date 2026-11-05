"""Ranking method round trips through per-user workflow settings."""
import pytest
import yaml
from fastapi.testclient import TestClient

import server.db as db
from server.user_paths import UserPaths
from .conftest import make_engine, register


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "engine", make_engine(tmp_path))
    from server.app import app
    with TestClient(app) as c:
        register(c, "ranking@example.com")
        UserPaths(user_id=1).ensure()
        yield c


def test_local_ranking_method_survives_a_save_and_reload(client):
    response = client.put("/api/llm-config", json={"tasks": {"ranking": {"method": "bm25"}}})
    assert response.status_code == 200, response.text
    assert client.get("/api/llm-config").json()["tasks"]["ranking"]["method"] == "bm25"
    saved = yaml.safe_load(UserPaths(user_id=1).config_path.read_text(encoding="utf-8"))
    assert saved["llm"]["tasks"]["ranking"] == {"method": "bm25"}


def test_ranking_can_switch_back_to_llm_without_losing_routing(client):
    for method in ("bm25", "llm"):
        response = client.put("/api/llm-config", json={"tasks": {"ranking": {
            "method": method, "primary": "groq", "fallbacks": ["gemini"],
            "models": {"groq": "test-model"}, "thinking": "off",
        }}})
        assert response.status_code == 200, response.text
        task = client.get("/api/llm-config").json()["tasks"]["ranking"]
        assert task["method"] == method
        assert task["primary"] == "groq"
        assert task["models"] == {"groq": "test-model"}


@pytest.mark.parametrize("task,method", [("ranking", "typo"), ("tailoring", "bm25")])
def test_invalid_ranking_methods_are_rejected_before_writing(client, task, method):
    path = UserPaths(user_id=1).config_path
    before = path.read_text(encoding="utf-8")
    response = client.put("/api/llm-config", json={"tasks": {task: {"method": method}}})
    assert response.status_code == 400
    assert path.read_text(encoding="utf-8") == before


def test_ranking_method_is_scoped_to_the_current_user(client):
    assert client.put("/api/llm-config", json={"tasks": {
        "ranking": {"method": "bm25"},
    }}).status_code == 200
    register(client, "other-ranking@example.com")
    other = client.get("/api/llm-config").json()["tasks"]["ranking"]
    assert other.get("method") in (None, "llm")
