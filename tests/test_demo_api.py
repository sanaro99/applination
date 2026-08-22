"""The demo door is public by necessity, so what it does and does not allow is
worth pinning down."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server.db as db
from server.demo import DEMO_EMAIL

from .conftest import make_engine, register


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "engine", make_engine(tmp_path))
    from server.app import app

    return app


@pytest.fixture()
def anon(app_env):
    with TestClient(app_env) as client:
        yield client


def test_health_advertises_the_demo(anon):
    body = anon.get("/api/health").json()
    assert body["ok"] is True
    assert body["demo"] is True


def test_demo_login_needs_no_credentials(anon):
    res = anon.post("/api/auth/demo")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["email"] == DEMO_EMAIL
    assert body["is_demo"] is True
    assert body["is_owner"] is False


def test_demo_login_yields_a_working_session(anon):
    anon.post("/api/auth/demo")
    me = anon.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["is_demo"] is True


def test_the_demo_session_can_read_the_seeded_data(anon):
    """The first call seeds on demand, so a visitor to a fresh install lands on
    a populated dashboard rather than on the empty state the demo exists to
    avoid."""
    anon.post("/api/auth/demo")
    apps = anon.get("/api/applications")
    assert apps.status_code == 200
    assert len(apps.json()) >= 8


def test_repeated_demo_logins_do_not_duplicate_the_data(anon):
    anon.post("/api/auth/demo")
    first = len(anon.get("/api/applications").json())
    anon.post("/api/auth/demo")
    assert len(anon.get("/api/applications").json()) == first


def test_an_ordinary_account_is_not_flagged_as_demo(app_env):
    with TestClient(app_env) as client:
        register(client, "real@example.com")
        assert client.get("/api/auth/me").json()["is_demo"] is False


def test_a_demo_visitor_cannot_read_another_account(app_env):
    """The demo is an ordinary account as far as scoping is concerned. This is
    the assertion that says so."""
    from server.db import Application, session

    with TestClient(app_env) as owner:
        real = register(owner, "real@example.com")
    with session() as s:
        # noscope: test fixture writing as a known non-demo user.
        s.add(Application(
            user_id=real["id"], company="Private Co", title="Engineer",
            folder_path="/tmp/private",
        ))
        s.commit()

    with TestClient(app_env) as visitor:
        visitor.post("/api/auth/demo")
        companies = {a["company"] for a in visitor.get("/api/applications").json()}
    assert "Private Co" not in companies


def test_demo_is_refused_when_disabled(anon, monkeypatch):
    monkeypatch.setenv("DEMO_ENABLED", "0")
    # 404 rather than 403: with the demo switched off the endpoint may as well
    # not exist.
    assert anon.post("/api/auth/demo").status_code == 404
    assert anon.get("/api/health").json()["demo"] is False


def test_the_demo_endpoint_is_declared_public(app_env):
    """It has to be in PUBLIC_PATHS or the middleware 401s it before the
    handler runs, and the structural guard in test_authz would flag it."""
    from server.app import PUBLIC_PATHS

    assert "/api/auth/demo" in PUBLIC_PATHS


def test_demo_is_rate_limited_per_ip_not_per_user(app_env):
    """The per-user LLM limit is a lockout on a shared account: one visitor
    would exhaust it for everyone. Simulated calls cost nothing, so the demo is
    keyed by IP instead."""
    from server.limits import _user_or_ip

    class Req:
        class state:
            user_id = 7
            is_demo = True

        client = type("c", (), {"host": "203.0.113.9"})()
        headers: dict = {}

    assert _user_or_ip(Req()).startswith("ip:")

    Req.state.is_demo = False
    assert _user_or_ip(Req()) == "user:7"
