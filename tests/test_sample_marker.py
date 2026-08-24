"""The sample-data marker.

Sample values silently becoming a real cover letter is the most likely way the
"use a sample" affordance turns into a bug report, so the marking is part of the
feature rather than polish on it.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server.db as db

from .conftest import make_engine, register


@pytest.fixture()
def client(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, "engine", engine)
    from server.app import app

    with TestClient(app) as c:
        register(c, "a@example.com")
        yield c


def test_status_starts_without_the_sample_flag(client):
    assert client.get("/api/onboarding/status").json()["sample_data"] is False


def test_marking_sample_data_persists(client):
    client.post("/api/onboarding/sample-used", json={"used": True})
    assert client.get("/api/onboarding/status").json()["sample_data"] is True


def test_clearing_the_marker_works(client):
    client.post("/api/onboarding/sample-used", json={"used": True})
    client.delete("/api/onboarding/sample-used")
    assert client.get("/api/onboarding/status").json()["sample_data"] is False


def test_the_marker_is_per_user(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, "engine", engine)
    from server.app import app

    with TestClient(app) as ca, TestClient(app) as cb:
        register(ca, "a@example.com")
        register(cb, "b@example.com")
        ca.post("/api/onboarding/sample-used", json={"used": True})
        assert cb.get("/api/onboarding/status").json()["sample_data"] is False
