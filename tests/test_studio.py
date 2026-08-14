"""Tests for per-workflow LLM routing + LLM-assisted content studio.

Config writes are isolated to a temp copy of config.yaml; the provider chain is
monkeypatched so no network calls happen.
"""
from __future__ import annotations

import shutil

import pytest
import yaml
from fastapi.testclient import TestClient

import server.db as db
from .conftest import migrate, register
import server.deps as deps
import server.config_api as config_api
import server.studio as studio
import src.providers as providers
from sqlalchemy import create_engine


class _FakeProvider:
    name = "fake"

    def json_call(self, system, user, max_tokens=2000, *, schema=None):
        return {
            "title": "Monitoring dashboard for 30+ teams",
            "tags": ["observability", "platform", "python", "splunk"],
            "role_fit": ["swe", "platform-engineer"],
            "company_fit": ["enterprise", "finance"],
            "one_liner": "Built a config-driven monitoring dashboard that cut detection time 60 percent.",
            "body": "Context. What I did with Splunk and ServiceNow. What mattered. Outcome with a real metric.",
        }

    def text_call(self, system, user, max_tokens=1000):
        return "summary_options:\n  - Updated summary line.\n"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    test_engine = create_engine(
        f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    migrate(test_engine)
    monkeypatch.setattr(db, "engine", test_engine)

    # Config is per-user now and lives under the (temp-redirected) users root,
    # so there is no real config.yaml left to corrupt. Seed the owner's copy
    # from the committed example, which is what the app itself does on first
    # run — the comment-preservation assertion below needs those comments.
    from server.user_paths import EXAMPLE_CONFIG_PATH, UserPaths

    owner_paths = UserPaths(user_id=1).ensure()
    shutil.copy(EXAMPLE_CONFIG_PATH, owner_paths.config_path)

    fake = _FakeProvider()
    monkeypatch.setattr(providers, "get_provider_chain", lambda cfg: [fake])
    monkeypatch.setattr(providers, "get_provider", lambda name, cfg, **k: fake)
    # Return no task chains so callers fall back to the (faked) global chain —
    # keeps tests offline instead of building real providers from config.
    monkeypatch.setattr(providers, "get_task_chains", lambda cfg: {})

    from server.app import app

    with TestClient(app) as c:
        # First account registered gets id 1, matching owner_paths above.
        register(c, "owner@example.com")
        yield c


def test_new_task_chains_exist():
    from src.providers.factory import _TASK_NAMES
    for t in ("coach", "interview", "essay", "content_studio"):
        assert t in _TASK_NAMES


def test_get_llm_config_shape(client):
    r = client.get("/api/llm-config")
    assert r.status_code == 200
    body = r.json()
    assert "global" in body and "tasks" in body and "providers" in body
    for t in ("coach", "interview", "essay", "content_studio"):
        assert t in body["task_names"]


def test_put_llm_config_preserves_comments_and_blocks(client):
    r = client.put(
        "/api/llm-config",
        json={
            "global": {"primary": "deepseek", "fallbacks": ["mistral", "gemini"]},
            "tasks": {
                "coach": {
                    "primary": "gemini",
                    "fallbacks": ["deepseek"],
                    "models": {"gemini": "gemini-2.5-flash"},
                }
            },
        },
    )
    assert r.status_code == 200

    from server.user_paths import UserPaths

    text = UserPaths(user_id=1).config_path.read_text(encoding="utf-8")
    # A representative comment + a provider block survive the round-trip.
    assert "Per-task provider chains" in text
    parsed = yaml.safe_load(text)
    assert "deepseek" in parsed["llm"] and "api_key" in parsed["llm"]["deepseek"]
    assert parsed["llm"]["tasks"]["coach"]["primary"] == "gemini"
    assert parsed["llm"]["tasks"]["coach"]["models"]["gemini"] == "gemini-2.5-flash"

    # GET reflects the new state.
    cfg = client.get("/api/llm-config").json()
    assert cfg["tasks"]["coach"]["primary"] == "gemini"


def test_put_llm_config_rejects_unknown_provider(client):
    r = client.put(
        "/api/llm-config",
        json={"global": {"primary": "not-a-provider", "fallbacks": []}, "tasks": {}},
    )
    assert r.status_code == 400


def test_generate_story_endpoint(client):
    r = client.post(
        "/api/master-data/stories/generate",
        json={"description": "A monitoring dashboard I built at UBS."},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["filename"]  # a slug
    # Returned markdown has parseable frontmatter with all required fields.
    text = body["text"].lstrip()
    assert text.startswith("---")
    _, fm, story_body = text.split("---", 2)
    front = yaml.safe_load(fm)
    for key in ("title", "tags", "role_fit", "company_fit", "one_liner"):
        assert key in front
    assert story_body.strip()


def test_tweak_endpoint_validates_kind(client):
    r = client.post(
        "/api/master-data/tweak",
        json={"kind": "bogus", "text": "x", "instruction": "y"},
    )
    assert r.status_code == 400


def test_tweak_resume_returns_valid_yaml(client):
    r = client.post(
        "/api/master-data/tweak",
        json={"kind": "resume", "text": "summary_options: [a]", "instruction": "tweak it"},
    )
    assert r.status_code == 200
    yaml.safe_load(r.json()["text"])  # parses


def test_content_studio_unit():
    from src.content_studio import (
        generate_story,
        slugify,
        story_dict_to_markdown,
        tweak_content,
    )

    fake = _FakeProvider()
    story = generate_story("desc", provider=fake, taxonomy="t", existing_titles=[])
    assert set(story) == {"title", "tags", "role_fit", "company_fit", "one_liner", "body"}
    md = story_dict_to_markdown(story)
    assert md.startswith("---")
    assert slugify("Hello, World! 2024") == "hello-world-2024"
    # text_call output (with code fences) is stripped.
    out = tweak_content("bio", "old", "make it warmer", provider=fake)
    assert "summary_options" in out
