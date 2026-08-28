"""The structured config editor behind the /config forms.

Two things make this file different from its master-data sibling. config.yaml
is seeded from a heavily commented template, so comment preservation is not a
nicety here — it is most of what the file is. And config.yaml is the one
document that carries API keys, which ``PUT /api/config`` diverts into
encrypted storage: a structured write must not undo that.
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


def config_text() -> str:
    return UserPaths(user_id=1).config_path.read_text(encoding="utf-8")


def on_disk() -> dict:
    return yaml.safe_load(config_text())


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #


def test_structured_get_returns_the_four_sections_the_form_owns(client):
    r = client.get("/api/config/structured")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert set(data) == {"search", "sources", "output", "reminders"}


def test_structured_get_reads_the_seeded_template(client):
    data = client.get("/api/config/structured").json()["data"]
    assert data["search"]["min_match_score"] == 55
    assert data["output"]["font_name"] == "Times New Roman"
    assert data["reminders"]["digest_enabled"] is False


def test_structured_get_lists_every_source_in_the_files_own_order(client):
    toggles = client.get("/api/config/structured").json()["data"]["sources"]["toggles"]
    keys = [t["key"] for t in toggles]
    assert keys[:2] == ["remotive", "themuse"]
    assert "greenhouse" in keys
    assert next(t for t in toggles if t["key"] == "adzuna")["enabled"] is False


def test_structured_get_never_hands_back_a_source_credential(client):
    """`sources` is a section the form owns, and two of its leaves are API
    keys. The form does not edit them, so it must not carry them either: this
    endpoint reads the redacted document, not the secret-merged one that
    `load_config` returns."""
    text = client.get("/api/config").json()["text"].replace(
        'rapidapi_key: ""', 'rapidapi_key: "rapid-123"'
    )
    client.put("/api/config", json={"text": text})

    body = client.get("/api/config/structured").text
    assert "rapid-123" not in body
    assert "rapidapi_key" not in body


def test_structured_get_requires_a_session(app_env):
    with TestClient(app_env) as anon:
        assert anon.get("/api/config/structured").status_code == 401


# --------------------------------------------------------------------------- #
# Write
# --------------------------------------------------------------------------- #


def put(client, section: str, values: dict):
    data = client.get("/api/config/structured").json()["data"]
    data[section] = {**data[section], **values}
    return client.put("/api/config/structured", json={"data": data})


def test_structured_put_writes_the_search_section(client):
    r = put(client, "search", {"min_match_score": 70, "keywords": ["sre intern"]})
    assert r.status_code == 200, r.text
    assert on_disk()["search"]["min_match_score"] == 70
    assert on_disk()["search"]["keywords"] == ["sre intern"]


def test_structured_put_keeps_the_templates_comments(client):
    """config.yaml is seeded from a 190-line commented template. A save that
    reformatted it into bare YAML would delete most of the file's value."""
    put(client, "search", {"max_jobs_per_day": 30})
    text = config_text()
    assert "# What kind of roles do you want?" in text
    assert "# Only keep jobs whose match_score >= this" in text


def test_structured_put_leaves_the_sections_it_does_not_own_alone(client):
    put(client, "output", {"produce_pdf": False})
    cfg = on_disk()
    assert cfg["llm"]["primary"] == "gemini"
    assert cfg["llm"]["tasks"]["ranking"]["thinking"] is False
    assert cfg["pricing"]["avoid_peak"] is True
    assert cfg["inbox"]["redirect_uri"].endswith("/api/inbox/oauth/callback")
    assert "user" in cfg


def test_a_stored_api_key_survives_a_structured_config_save(client):
    """The trap. `PUT /api/config` moves keys into encrypted storage and blanks
    them in the file; a structured write goes through the same door, so a key
    stored earlier must still be there — and must still be merged back by
    load_config — after the form saves."""
    from server.deps import load_config
    from server.user_secrets import secret_names

    text = client.get("/api/config").json()["text"].replace(
        'gemini:\n    api_key: ""', 'gemini:\n    api_key: "sk-real-key"'
    )
    assert client.put("/api/config", json={"text": text}).status_code == 200
    assert "llm.gemini.api_key" in secret_names(1)

    assert put(client, "search", {"min_match_score": 61}).status_code == 200

    assert "sk-real-key" not in config_text()
    assert "llm.gemini.api_key" in secret_names(1)

    class _U:
        id = 1

    assert load_config(_U())["llm"]["gemini"]["api_key"] == "sk-real-key"


def test_a_stored_source_credential_survives_too(client):
    """`sources` is the section the form *does* own, and two of its leaves are
    secrets. Writing the toggles must not reach them."""
    from server.user_secrets import secret_names

    text = client.get("/api/config").json()["text"].replace(
        'rapidapi_key: ""', 'rapidapi_key: "rapid-123"'
    )
    assert client.put("/api/config", json={"text": text}).status_code == 200
    assert "sources.jsearch.rapidapi_key" in secret_names(1)

    data = client.get("/api/config/structured").json()["data"]
    data["sources"]["toggles"] = [
        {**t, "enabled": True} for t in data["sources"]["toggles"]
    ]
    assert client.put("/api/config/structured", json={"data": data}).status_code == 200

    assert "sources.jsearch.rapidapi_key" in secret_names(1)
    assert "rapid-123" not in config_text()
    assert on_disk()["sources"]["jsearch"]["enabled"] is True


def test_source_toggles_round_trip(client):
    data = client.get("/api/config/structured").json()["data"]
    data["sources"]["toggles"] = [
        {"key": "remotive", "enabled": False},
        {"key": "lever", "enabled": True},
    ]
    assert client.put("/api/config/structured", json={"data": data}).status_code == 200
    cfg = on_disk()
    assert cfg["sources"]["remotive"]["enabled"] is False
    assert cfg["sources"]["lever"]["enabled"] is True
    # Untouched, because it was not in the payload.
    assert cfg["sources"]["themuse"]["enabled"] is True


def test_an_unknown_source_is_ignored_rather_than_invented(client):
    """A toggle for a scraper the config has no block for would be a config key
    that means nothing to `main.fetch_all`."""
    data = client.get("/api/config/structured").json()["data"]
    data["sources"]["toggles"] = [{"key": "not_a_scraper", "enabled": True}]
    assert client.put("/api/config/structured", json={"data": data}).status_code == 200
    assert "not_a_scraper" not in on_disk()["sources"]


def test_the_greenhouse_slug_list_round_trips(client):
    data = client.get("/api/config/structured").json()["data"]
    data["sources"]["greenhouse_extra_companies"] = ["stripe", "figma"]
    assert client.put("/api/config/structured", json={"data": data}).status_code == 200
    assert on_disk()["sources"]["greenhouse"]["extra_companies"] == ["stripe", "figma"]


def test_output_and_reminders_round_trip(client):
    put(client, "output", {"font_name": "Calibri", "base_font_size": 11.0})
    put(client, "reminders", {"digest_enabled": True, "follow_up_days": 4})
    cfg = on_disk()
    assert cfg["output"]["font_name"] == "Calibri"
    assert cfg["output"]["base_font_size"] == 11.0
    assert cfg["reminders"]["digest_enabled"] is True
    assert cfg["reminders"]["follow_up_days"] == 4


def test_a_no_op_save_keeps_every_value_and_the_quoting_around_it(client):
    """Not byte equality on the first save: ruamel re-indents sequences on any
    round trip, which `update_config` has always done. What must hold is that
    nothing the user did not change is rewritten — including the template's
    quoting, which only survives if untouched keys are left alone rather than
    reassigned to an equal plain value."""
    data = client.get("/api/config/structured").json()["data"]
    assert client.put("/api/config/structured", json={"data": data}).status_code == 200
    text = config_text()
    assert 'font_name: "Times New Roman"' in text
    assert yaml.safe_load(text)["search"]["keywords"] == data["search"]["keywords"]

    before = text
    assert client.put("/api/config/structured", json={"data": data}).status_code == 200
    assert config_text() == before


def test_an_out_of_range_score_is_rejected_by_name(client):
    r = put(client, "search", {"min_match_score": 400})
    assert r.status_code == 400
    assert "min_match_score" in r.json()["detail"]


def test_an_empty_font_name_is_rejected_by_name(client):
    r = put(client, "output", {"font_name": "   "})
    assert r.status_code == 400
    assert "font_name" in r.json()["detail"]


def test_a_rejected_save_does_not_touch_the_file(client):
    client.get("/api/config/structured")
    before = config_text()
    put(client, "search", {"max_jobs_per_day": 0})
    assert config_text() == before


def test_structured_put_requires_a_session(app_env):
    with TestClient(app_env) as anon:
        r = anon.put("/api/config/structured", json={"data": {}})
        assert r.status_code == 401
