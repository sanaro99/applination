"""The profile meter's data model.

Two phases, both honest: formation genuinely completes at 100%, and only then
does the card switch to story coverage. A bar engineered never to fill is a
dark pattern, so nothing here may produce one.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server.db as db
from server.intake import save_draft_story
from server.profile_strength import compute
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


def _user(uid: int = 1):
    from server.db import User, session

    with session() as s:
        return s.get(User, uid)  # noscope: test helper, explicit id


def test_a_fresh_account_has_nine_empty_ridges(client):
    out = compute(_user())
    assert out["total"] == 9
    assert out["filled"] == 0
    assert out["phase"] == "formation"
    assert [r["id"] for r in out["parts"]] == [
        "contact", "material", "resume", "story_1", "story_2",
        "story_3", "voice", "search", "provider",
    ]


def test_a_draft_story_is_a_partial_ridge_not_a_filled_one(client):
    save_draft_story(UserPaths(user_id=1).ensure(), "A story", "body text")
    out = compute(_user())
    states = {r["id"]: r["state"] for r in out["parts"]}
    assert states["story_1"] == "partial"
    assert states["material"] == "filled"
    assert 0 < out["score"] < 1


def test_a_real_story_fills_the_ridge(client):
    paths = UserPaths(user_id=1).ensure()
    (paths.stories_dir / "real.md").write_text(
        '---\ntitle: "Real"\ntags: [backend, python]\n---\n\nBody.\n', encoding="utf-8"
    )
    out = compute(_user())
    states = {r["id"]: r["state"] for r in out["parts"]}
    assert states["story_1"] == "filled"


def test_next_names_the_first_unfinished_ridge(client):
    out = compute(_user())
    assert out["next"]["id"] == "contact"
    assert out["next"]["hint"]


def test_score_is_zero_to_one(client):
    out = compute(_user())
    assert 0.0 <= out["score"] <= 1.0


def test_coverage_reports_tags_the_stories_actually_carry(client):
    paths = UserPaths(user_id=1).ensure()
    (paths.stories_dir / "real.md").write_text(
        '---\ntitle: "Real"\ntags: [backend, python]\n---\n\nBody.\n', encoding="utf-8"
    )
    out = compute(_user())
    assert "backend" in out["coverage"]["covered"]
    assert "python" in out["coverage"]["covered"]
    assert "backend" not in out["coverage"]["gaps"]


def test_coverage_names_the_size_of_the_taxonomy_it_measures_against(client):
    """Gaps are a capped sample, so covered + gaps is not the whole vocabulary.

    Without the total the card can only say "2 tags covered" — a number with no
    denominator, which tells the user nothing about whether that is most of the
    taxonomy or a corner of it.
    """
    paths = UserPaths(user_id=1).ensure()
    (paths.stories_dir / "real.md").write_text(
        '---\ntitle: "Real"\ntags: [backend, python]\n---\n\nBody.\n', encoding="utf-8"
    )
    out = compute(_user())
    coverage = out["coverage"]
    assert coverage["total"] > 0
    assert coverage["total"] >= len(coverage["covered"]) + len(coverage["gaps"])


def test_coverage_on_an_empty_account_is_empty_not_an_error(client):
    out = compute(_user())
    assert out["coverage"]["covered"] == []


def test_endpoint_returns_the_model(client):
    r = client.get("/api/profile/strength")
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 9


def test_endpoint_requires_a_session(app_env):
    with TestClient(app_env) as anon:
        assert anon.get("/api/profile/strength").status_code == 401


def test_onboarding_status_still_works_after_the_refactor(client):
    r = client.get("/api/onboarding/status")
    assert r.status_code == 200, r.text
    assert "steps" in r.json() and "intake" in r.json()


# --- Template defaults are not user choices ---------------------------------
#
# ``UserPaths.ensure`` seeds every new account from config.example.yaml, which
# ships example search keywords and an Ollama base_url. Counting either as
# evidence would hand a brand-new account two filled parts it never earned.


def test_seeded_example_keywords_do_not_fill_the_search_ridge(client):
    out = compute(_user())
    states = {r["id"]: r["state"] for r in out["parts"]}
    assert states["search"] == "empty"


def test_the_users_own_keywords_do_fill_it(client):
    r = client.put(
        "/api/onboarding/search",
        json={"keywords": ["backend engineer", "platform engineer"]},
    )
    assert r.status_code == 200, r.text
    states = {r["id"]: r["state"] for r in compute(_user())["parts"]}
    assert states["search"] == "filled"


def test_seeded_ollama_base_url_does_not_fill_the_provider_ridge(client):
    out = compute(_user())
    states = {r["id"]: r["state"] for r in out["parts"]}
    assert states["provider"] == "empty"


def test_choosing_ollama_fills_the_provider_ridge(client):
    r = client.put(
        "/api/onboarding/provider",
        json={"provider": "ollama", "base_url": "http://localhost:11434"},
    )
    assert r.status_code == 200, r.text
    states = {r["id"]: r["state"] for r in compute(_user())["parts"]}
    assert states["provider"] == "filled"


def test_a_stored_api_key_fills_the_provider_ridge(client):
    r = client.put(
        "/api/onboarding/provider",
        json={"provider": "gemini", "api_key": "AIza-not-a-real-key-000000000"},
    )
    assert r.status_code == 200, r.text
    states = {r["id"]: r["state"] for r in compute(_user())["parts"]}
    assert states["provider"] == "filled"
