"""Provider setup metadata.

Staleness is the risk this file exists to manage: instructions rot, vendors
redesign consoles, and free tiers narrow. The tests enforce the two rules that
keep the copy durable — deep links instead of click paths, and never a number.
"""
from __future__ import annotations

import re
from datetime import date

import pytest
from fastapi.testclient import TestClient

import server.db as db
from server.provider_setup import PROVIDERS, stale

from .conftest import make_engine, register


@pytest.fixture()
def client(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, "engine", engine)
    from server.app import app

    with TestClient(app) as c:
        register(c, "a@example.com")
        yield c


def test_exactly_one_provider_is_recommended():
    assert sum(1 for p in PROVIDERS if p["recommended"]) == 1


def test_gemini_is_the_recommended_one():
    recommended = next(p for p in PROVIDERS if p["recommended"])
    assert recommended["id"] == "gemini"


def test_gemini_is_listed_first():
    assert PROVIDERS[0]["id"] == "gemini"


def test_every_provider_has_the_required_fields():
    required = {
        "id", "label", "recommended", "why", "model", "console_url",
        "steps", "key_shape", "cost_note", "needs_key", "verified_on",
    }
    for p in PROVIDERS:
        assert required <= set(p), f"{p['id']} is missing {required - set(p)}"


def test_steps_stay_shallow():
    """Three lines survives a vendor redesign; a nine-step click path does not."""
    for p in PROVIDERS:
        assert 0 < len(p["steps"]) <= 3, p["id"]


def test_no_copy_quotes_a_number():
    """Quotas and prices go stale. Gemini's free tier narrowed to Flash-only
    while this feature was being designed."""
    digits = re.compile(r"\d")
    for p in PROVIDERS:
        assert not digits.search(p["cost_note"]), p["id"]
        assert not digits.search(p["why"]), p["id"]
        for step in p["steps"]:
            assert not digits.search(step), p["id"]


def test_console_urls_are_https_deep_links():
    for p in PROVIDERS:
        if not p["needs_key"]:
            continue
        assert p["console_url"].startswith("https://"), p["id"]


def test_verified_on_parses_as_a_date():
    for p in PROVIDERS:
        date.fromisoformat(p["verified_on"])


def test_stale_flags_old_entries():
    assert stale({"verified_on": "2020-01-01"}, today=date(2026, 8, 24)) is True
    assert stale({"verified_on": "2026-08-01"}, today=date(2026, 8, 24)) is False


def test_endpoint_returns_providers_with_a_stale_flag(client):
    r = client.get("/api/providers/setup")
    assert r.status_code == 200, r.text
    body = r.json()["providers"]
    assert body[0]["id"] == "gemini"
    assert "stale" in body[0]


def test_endpoint_requires_a_session(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, "engine", engine)
    from server.app import app

    with TestClient(app) as anon:
        assert anon.get("/api/providers/setup").status_code == 401
