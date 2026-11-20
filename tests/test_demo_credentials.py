"""The demo is one account shared by every visitor, so nothing a visitor
attaches to it may be handed to the next one: no API keys, no Gmail token, no
paired extension or local Ollama worker."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server.db as db
from server.demo import DEMO_EMAIL, ensure_demo_user, seed_demo
from server.user_secrets import secret_names

from .conftest import make_engine, register


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "engine", make_engine(tmp_path))
    from server.app import app

    return app


@pytest.fixture()
def demo(app_env):
    with TestClient(app_env) as client:
        assert client.post("/api/auth/demo").status_code == 200
        yield client


def _demo_id() -> int:
    from sqlmodel import select

    with db.session() as s:
        return s.exec(select(db.User).where(db.User.email == DEMO_EMAIL)).one().id


def test_demo_cannot_store_a_provider_key(demo):
    res = demo.put("/api/onboarding/provider",
                   json={"provider": "deepseek", "api_key": "sk-visitor-secret-1234"})
    assert res.status_code == 403
    assert "demo" in res.json()["detail"].lower()
    assert secret_names(_demo_id()) == []


def test_demo_cannot_smuggle_a_key_through_the_raw_config(demo):
    text = demo.get("/api/config").json()["text"]
    assert "api_key" in text
    res = demo.put("/api/config", json={"text": text.replace('api_key: ""', 'api_key: "sk-smuggled-5678"', 1)})
    assert res.status_code == 403
    assert secret_names(_demo_id()) == []
    assert "sk-smuggled" not in demo.get("/api/config").json()["text"]


def test_demo_cannot_approve_an_extension_pairing(demo):
    code = demo.post("/api/extension/pair/start").json()["user_code"]
    res = demo.post("/api/extension/pair/approve", json={"user_code": code})
    assert res.status_code == 403


def test_ordinary_accounts_still_store_keys(app_env):
    with TestClient(app_env) as client:
        user = register(client, "real@example.com")
        res = client.put("/api/onboarding/provider",
                         json={"provider": "deepseek", "api_key": "sk-real-key-9999"})
        assert res.status_code == 200, res.text
        assert "llm.deepseek.api_key" in secret_names(user["id"])


def test_nightly_restore_drops_credentials_left_on_the_demo(app_env):
    from server.crypto import encrypt

    seed_demo()
    user_id = ensure_demo_user()
    with db.session() as s:
        # Simulate a key stored before the guard existed.
        s.add(db.UserSecret(user_id=user_id, name="llm.deepseek.api_key", ciphertext=encrypt("sk-old")))
        s.commit()
    assert secret_names(user_id) == ["llm.deepseek.api_key"]
    seed_demo()
    assert secret_names(user_id) == []
