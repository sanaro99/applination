"""Tests for the Coach conversational assistant (server/chat.py +
server/coach_context.py). DB is isolated to a temp SQLite file and the LLM
provider chain is monkeypatched to a fake, so no network calls happen.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

import server.db as db
from .conftest import migrate
import src.providers as providers


class _FakeProvider:
    name = "fake"

    def __init__(self, reply: str = "Here is a grounded reply about AutoFlow."):
        self._reply = reply

    def text_call(self, system: str, user: str, max_tokens: int = 1000) -> str:
        return self._reply


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Isolate the DB to a temp file by swapping the module-level engine.
    test_engine = create_engine(
        f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    migrate(test_engine)
    monkeypatch.setattr(db, "engine", test_engine)

    # Fake out the provider chain so post_message never hits the network.
    monkeypatch.setattr(providers, "get_provider_chain", lambda cfg: [_FakeProvider()])
    # Empty task chains → callers fall back to the faked global chain (offline).
    monkeypatch.setattr(providers, "get_task_chains", lambda cfg: {})

    from server.app import app

    with TestClient(app) as c:  # triggers startup → init_db() on test_engine
        yield c


def test_tables_created(client):
    names = set(inspect(db.engine).get_table_names())
    assert {"chatsession", "chatmessage", "savedanswer"} <= names
    cols = {c["name"] for c in inspect(db.engine).get_columns("chatsession")}
    assert "mode" in cols


def test_session_crud(client):
    r = client.post("/api/chat/sessions", json={})
    assert r.status_code == 200
    sid = r.json()["id"]
    assert r.json()["title"] == "New chat"

    assert any(s["id"] == sid for s in client.get("/api/chat/sessions").json())

    r = client.patch(f"/api/chat/sessions/{sid}", json={"title": "My prep"})
    assert r.json()["title"] == "My prep"

    assert client.delete(f"/api/chat/sessions/{sid}").json() == {"ok": True}
    assert client.get(f"/api/chat/sessions/{sid}").status_code == 404


def test_post_message_persists_both_turns(client):
    sid = client.post("/api/chat/sessions", json={}).json()["id"]

    r = client.post(
        f"/api/chat/sessions/{sid}/messages",
        json={"content": "What is my strongest backend project?"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["user_message"]["role"] == "user"
    assert body["assistant_message"]["role"] == "assistant"
    assert "AutoFlow" in body["assistant_message"]["content"]

    detail = client.get(f"/api/chat/sessions/{sid}").json()
    assert len(detail["messages"]) == 2
    # First user message auto-titles the session.
    assert detail["session"]["title"].startswith("What is my strongest")
    assert detail["session"]["message_count"] == 2


def test_empty_message_rejected(client):
    sid = client.post("/api/chat/sessions", json={}).json()["id"]
    r = client.post(f"/api/chat/sessions/{sid}/messages", json={"content": "  "})
    assert r.status_code == 400


def test_build_coach_prompt_is_grounded():
    from server.coach_context import (
        build_coach_prompt,
        load_profile_bundle,
        pick_stories,
    )

    bundle = load_profile_bundle()
    stories = pick_stories(
        bundle, question="Tell me about a backend system you built", app=None
    )
    assert len(stories) <= 3

    system, user = build_coach_prompt(
        bundle,
        question="Tell me about a backend system you built",
        history=[],
        app=None,
        stories=stories,
        user={"full_name": "Sanchit Arora"},
    )
    # Anti-fabrication + voice language is carried over from tailor.py.
    assert "Never invent" in system
    assert "Sanchit" in system
    assert "STORY MATERIAL" in user
    assert "PROFILE SUMMARY" in user


def test_session_mode_and_grounding(client, tmp_path):
    # Interview-mode session round-trips with the right default title.
    r = client.post("/api/chat/sessions", json={"mode": "interview"})
    assert r.status_code == 200
    sid = r.json()["id"]
    assert r.json()["mode"] == "interview"
    assert r.json()["title"] == "New interview"

    # Filtered listing only returns interview sessions.
    chat_sid = client.post("/api/chat/sessions", json={}).json()["id"]
    interview_ids = {s["id"] for s in client.get("/api/chat/sessions?mode=interview").json()}
    assert sid in interview_ids and chat_sid not in interview_ids

    # Create an application and ground/clear it via PATCH.
    folder = tmp_path / "app1"
    folder.mkdir()
    with db.session() as s:
        app_row = db.Application(company="Acme", title="SWE", folder_path=str(folder))
        s.add(app_row)
        s.commit()
        s.refresh(app_row)
        app_id = app_row.id

    r = client.patch(f"/api/chat/sessions/{sid}", json={"application_id": app_id})
    assert r.json()["application_id"] == app_id
    assert r.json()["application_label"] == "Acme — SWE"
    # Explicit null clears grounding.
    r = client.patch(f"/api/chat/sessions/{sid}", json={"application_id": None})
    assert r.json()["application_id"] is None


def test_interview_kickoff(client):
    sid = client.post("/api/chat/sessions", json={"mode": "interview"}).json()["id"]
    r = client.post(f"/api/chat/sessions/{sid}/kickoff")
    assert r.status_code == 200
    assert r.json()["role"] == "assistant"
    # One assistant message now exists; a second kickoff is rejected.
    assert len(client.get(f"/api/chat/sessions/{sid}").json()["messages"]) == 1
    assert client.post(f"/api/chat/sessions/{sid}/kickoff").status_code == 400

    # Kickoff on a chat-mode session is rejected.
    chat_sid = client.post("/api/chat/sessions", json={}).json()["id"]
    assert client.post(f"/api/chat/sessions/{chat_sid}/kickoff").status_code == 400


def test_interview_post_message_persists(client):
    sid = client.post("/api/chat/sessions", json={"mode": "interview"}).json()["id"]
    client.post(f"/api/chat/sessions/{sid}/kickoff")
    r = client.post(
        f"/api/chat/sessions/{sid}/messages",
        json={"content": "I built AutoFlow to cut setup time."},
    )
    assert r.status_code == 200
    # kickoff (1) + user (1) + assistant (1) = 3
    assert len(client.get(f"/api/chat/sessions/{sid}").json()["messages"]) == 3


def test_essay_endpoint(client):
    r = client.post(
        "/api/chat/essay",
        json={"prompt": "Why do you deserve this scholarship?", "word_limit": 150},
    )
    assert r.status_code == 200
    assert "AutoFlow" in r.json()["content"]
    assert client.post("/api/chat/essay", json={"prompt": "  "}).status_code == 400


def test_interview_and_essay_prompts_grounded():
    from server.coach_context import (
        build_essay_prompt,
        build_interview_kickoff_prompt,
        load_profile_bundle,
        pick_stories,
    )

    bundle = load_profile_bundle()
    stories = pick_stories(bundle, question="leadership", app=None)

    sys_i, _ = build_interview_kickoff_prompt(
        bundle, app=None, stories=stories, user={"full_name": "Sanchit Arora"}
    )
    assert "Never invent" in sys_i and "Sanchit" in sys_i

    sys_e, user_e = build_essay_prompt(
        bundle, prompt="Why you?", word_limit=120, instructions="",
        app=None, stories=stories, user={"full_name": "Sanchit Arora"},
    )
    assert "Never invent" in sys_e
    assert "120 words" in user_e


def test_answer_bank_save_list_attach(client, tmp_path):
    # Save an answer.
    r = client.post(
        "/api/chat/answers",
        json={"content": "I led AutoFlow at UBS.", "title": "Backend story",
              "tags": ["behavioral"]},
    )
    assert r.status_code == 200
    aid = r.json()["id"]
    assert r.json()["tags"] == ["behavioral"]

    assert any(a["id"] == aid for a in client.get("/api/chat/answers").json())

    # Create an Application with a real on-disk folder to attach into.
    folder = tmp_path / "2026-05-31" / "UBS_Engineer"
    folder.mkdir(parents=True)
    with db.session() as s:
        app_row = db.Application(
            company="UBS", title="Engineer", folder_path=str(folder),
        )
        s.add(app_row)
        s.commit()
        s.refresh(app_row)
        app_id = app_row.id

    r = client.post(
        f"/api/chat/answers/{aid}/attach", json={"application_id": app_id}
    )
    assert r.status_code == 200
    answers_md = folder / "answers.md"
    assert answers_md.exists()
    assert "I led AutoFlow at UBS." in answers_md.read_text(encoding="utf-8")

    # The saved answer is now linked to the application.
    linked = client.get(f"/api/chat/answers?application_id={app_id}").json()
    assert any(a["id"] == aid for a in linked)
