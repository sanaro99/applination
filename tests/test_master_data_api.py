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


def test_structured_get_returns_the_parsed_document(client):
    client.put(
        "/api/master-data/resume",
        json={"text": "core_skills:\n  - Python\nsummary_options:\n  - Engineer\n"},
    )
    r = client.get("/api/master-data/resume/structured")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["core_skills"] == ["Python"]


def test_structured_get_normalizes_the_old_skills_list(client):
    """Guards PR #57: a file written before the shape was settled must still
    load, not crash the form."""
    client.put(
        "/api/master-data/resume",
        json={"text": "skills:\n  - group: languages\n    items:\n      - Python\n"},
    )
    r = client.get("/api/master-data/resume/structured")
    assert r.json()["data"]["skills"] == {"languages": ["Python"]}


def test_structured_get_on_an_account_with_no_resume_is_empty_not_404(client):
    r = client.get("/api/master-data/resume/structured")
    assert r.status_code == 200
    assert r.json()["data"] == {}


def test_structured_get_requires_a_session(app_env):
    with TestClient(app_env) as anon:
        r = anon.get("/api/master-data/resume/structured")
        assert r.status_code == 401


VALID = {
    "summary_options": ["Engineer"],
    "core_skills": ["Python"],
    "skills": {"languages": ["Python"]},
    "experience": [
        {"company": "X", "role": "Software Engineer", "bullets_all": ["Shipped a thing."]}
    ],
    "education": [{"school": "U", "degree": "BS CS"}],
}


def test_structured_put_writes_the_file(client):
    r = client.put("/api/master-data/resume/structured", json={"data": VALID})
    assert r.status_code == 200, r.text
    on_disk = yaml.safe_load(
        UserPaths(user_id=1).resume_path.read_text(encoding="utf-8")
    )
    assert on_disk["core_skills"] == ["Python"]
    assert on_disk["skills"] == {"languages": ["Python"]}


def test_a_no_op_save_neither_reorders_nor_drops_keys(client):
    client.put("/api/master-data/resume/structured", json={"data": VALID})
    first = client.get("/api/master-data/resume/structured").json()["data"]
    client.put("/api/master-data/resume/structured", json={"data": first})
    second = client.get("/api/master-data/resume/structured").json()["data"]
    assert second == first
    assert list(second) == list(first)


def test_structured_put_preserves_a_comment_added_through_the_text_editor(client):
    client.put(
        "/api/master-data/resume",
        json={"text": "# hands off\ncore_skills:\n  - Python\nprivate: yes\n"},
    )
    client.put("/api/master-data/resume/structured", json={"data": VALID})
    on_disk = UserPaths(user_id=1).resume_path.read_text(encoding="utf-8")
    assert "# hands off" in on_disk
    assert yaml.safe_load(on_disk)["private"] is True


def test_a_missing_required_field_is_rejected_by_name(client):
    broken = {
        **VALID,
        "experience": [{"role": "Software Engineer", "bullets_all": ["x"]}],
    }
    r = client.put("/api/master-data/resume/structured", json={"data": broken})
    assert r.status_code == 400
    assert "experience[0]" in r.json()["detail"]
    assert "company" in r.json()["detail"]


def test_a_wrong_type_is_rejected_by_path(client):
    broken = {**VALID, "core_skills": "Python"}
    r = client.put("/api/master-data/resume/structured", json={"data": broken})
    assert r.status_code == 400
    assert "core_skills" in r.json()["detail"]


def test_a_rejected_save_does_not_touch_the_file(client):
    client.put("/api/master-data/resume", json={"text": "core_skills:\n  - Original\n"})
    client.put(
        "/api/master-data/resume/structured",
        json={"data": {**VALID, "core_skills": "not a list"}},
    )
    on_disk = yaml.safe_load(
        UserPaths(user_id=1).resume_path.read_text(encoding="utf-8")
    )
    assert on_disk["core_skills"] == ["Original"]


def test_structured_and_text_views_agree_on_the_same_file(client):
    client.put("/api/master-data/resume/structured", json={"data": VALID})
    text = client.get("/api/master-data/resume").json()["text"]
    structured = client.get("/api/master-data/resume/structured").json()["data"]
    assert yaml.safe_load(text)["core_skills"] == structured["core_skills"]


def test_structured_put_requires_a_session(app_env):
    with TestClient(app_env) as anon:
        r = anon.put("/api/master-data/resume/structured", json={"data": VALID})
        assert r.status_code == 401


def test_mapping_shaped_skills_are_accepted_even_though_the_schema_wants_a_list(client):
    """The schema and the disk format disagree about `skills` on purpose. If
    this fails, someone has "fixed" one of the two shapes and broken the other."""
    r = client.put(
        "/api/master-data/resume/structured",
        json={"data": {**VALID, "skills": {"languages": ["Python"], "data": ["SQL"]}}},
    )
    assert r.status_code == 200, r.text
    on_disk = yaml.safe_load(
        UserPaths(user_id=1).resume_path.read_text(encoding="utf-8")
    )
    assert on_disk["skills"] == {"languages": ["Python"], "data": ["SQL"]}


# --------------------------------------------------------------------------- #
# The tag taxonomy
#
# Served rather than duplicated in TypeScript: `_INDEX.md` is a committed file
# that says "expand as needed", and a copy in the browser would go stale the
# first time somebody takes it up on that.
# --------------------------------------------------------------------------- #


def test_the_taxonomy_is_served_grouped_and_labelled(client):
    r = client.get("/api/master-data/story-taxonomy")
    assert r.status_code == 200, r.text
    groups = r.json()["groups"]
    assert groups, "the committed _INDEX.md should parse into groups"
    assert {"label", "field", "tags"} <= set(groups[0])


def test_the_taxonomy_says_which_field_each_group_feeds(client):
    groups = client.get("/api/master-data/story-taxonomy").json()["groups"]
    fields = {g["field"] for g in groups}
    assert "role_fit" in fields
    assert "company_fit" in fields
    assert "tags" in fields


def test_the_taxonomy_requires_a_session(app_env):
    with TestClient(app_env) as anon:
        assert anon.get("/api/master-data/story-taxonomy").status_code == 401


# --------------------------------------------------------------------------- #
# Stories, structured
# --------------------------------------------------------------------------- #

STORY = """---
title: "Monitoring dashboard"
tags: [platform, devtools]
role_fit: [swe]
company_fit: [enterprise]
one_liner: "Cut detection time by 60% for 30+ teams."
---

**Context**: teams had no shared view.
"""


def test_structured_story_get_splits_frontmatter_from_body(client):
    client.put("/api/master-data/stories/dash", json={"text": STORY})
    r = client.get("/api/master-data/stories/dash/structured")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["tags"] == ["platform", "devtools"]
    assert data["body"].startswith("**Context**")


def test_structured_story_get_404s_on_a_story_that_does_not_exist(client):
    assert client.get("/api/master-data/stories/nope/structured").status_code == 404


def test_structured_story_put_writes_a_file_the_matcher_can_read(client):
    client.put("/api/master-data/stories/dash", json={"text": STORY})
    r = client.put(
        "/api/master-data/stories/dash/structured",
        json={"data": {"tags": ["sre", "observability"], "body": "New body."}},
    )
    assert r.status_code == 200, r.text
    text = client.get("/api/master-data/stories/dash").json()["text"]
    fm = yaml.safe_load(text.split("---", 2)[1])
    assert fm["tags"] == ["sre", "observability"]
    assert fm["title"] == "Monitoring dashboard"
    assert "New body." in text


def test_an_off_taxonomy_tag_is_accepted(client):
    """The taxonomy says "expand as needed". Refusing a tag it does not list
    would make the picker a cage; the UI marks it instead."""
    client.put("/api/master-data/stories/dash", json={"text": STORY})
    r = client.put(
        "/api/master-data/stories/dash/structured",
        json={"data": {"tags": ["quantum-annealing"]}},
    )
    assert r.status_code == 200, r.text
    assert (
        client.get("/api/master-data/stories/dash/structured").json()["data"]["tags"]
        == ["quantum-annealing"]
    )


def test_a_wrong_type_is_rejected_by_name(client):
    client.put("/api/master-data/stories/dash", json={"text": STORY})
    r = client.put(
        "/api/master-data/stories/dash/structured", json={"data": {"tags": 3}}
    )
    assert r.status_code == 400
    assert "tags" in r.json()["detail"]


def test_a_rejected_story_save_does_not_touch_the_file(client):
    client.put("/api/master-data/stories/dash", json={"text": STORY})
    client.put(
        "/api/master-data/stories/dash/structured", json={"data": {"title": ["a"]}}
    )
    text = client.get("/api/master-data/stories/dash").json()["text"]
    assert "Monitoring dashboard" in text


def test_structured_and_text_story_views_agree(client):
    client.put("/api/master-data/stories/dash", json={"text": STORY})
    client.put(
        "/api/master-data/stories/dash/structured",
        json={"data": {"one_liner": "A new hook."}},
    )
    text = client.get("/api/master-data/stories/dash").json()["text"]
    data = client.get("/api/master-data/stories/dash/structured").json()["data"]
    assert data["one_liner"] == "A new hook."
    assert "A new hook." in text


def test_structured_story_endpoints_reject_a_traversing_name(client):
    """A forward slash never reaches the handler — the router sees extra path
    segments and 404s. A backslash does, and only `_check_story_name` stops it
    from writing outside the account's own stories directory."""
    assert (
        client.get("/api/master-data/stories/..%5C..%5Cx/structured").status_code == 400
    )
    assert (
        client.put(
            "/api/master-data/stories/..%5C..%5Cx/structured", json={"data": {}}
        ).status_code
        == 400
    )


def test_structured_story_endpoints_require_a_session(app_env):
    with TestClient(app_env) as anon:
        assert anon.get("/api/master-data/stories/dash/structured").status_code == 401
        assert (
            anon.put(
                "/api/master-data/stories/dash/structured", json={"data": {}}
            ).status_code
            == 401
        )
