"""Reading and writing one story file as frontmatter + body.

Same split as the master resume: tolerant on the way in, so a half-finished
file still opens in the form, and lossless on the way out, so nothing the form
does not render gets deleted.
"""
from __future__ import annotations

from src.story_doc import parse_story, render_story

SAMPLE = """---
title: "Monitoring dashboard"
tags: [platform, devtools]
role_fit: [swe]
company_fit: [enterprise]
one_liner: "Cut detection time by 60% for 30+ teams."
---

**Context**: teams had no shared view.

**What I did**: built one.
"""


def test_parses_the_frontmatter_fields():
    doc = parse_story(SAMPLE)
    assert doc["title"] == "Monitoring dashboard"
    assert doc["tags"] == ["platform", "devtools"]
    assert doc["role_fit"] == ["swe"]
    assert doc["company_fit"] == ["enterprise"]
    assert doc["one_liner"].startswith("Cut detection")


def test_the_body_is_everything_after_the_closing_fence():
    doc = parse_story(SAMPLE)
    assert doc["body"].startswith("**Context**")
    assert "**What I did**" in doc["body"]
    assert "---" not in doc["body"]


def test_a_file_with_no_frontmatter_is_all_body():
    doc = parse_story("Just some prose.\n")
    assert doc["body"] == "Just some prose."
    assert doc["tags"] == []
    assert doc["title"] == ""


def test_a_single_string_where_a_list_belongs_is_read_as_one_item():
    """A hand-edited file can say ``tags: platform``. The form indexes these
    lists, so the one outcome this must never produce is a surprise type."""
    doc = parse_story("---\ntags: platform\n---\n\nBody.\n")
    assert doc["tags"] == ["platform"]


def test_an_empty_file_is_an_empty_document():
    doc = parse_story("")
    assert doc == {
        "title": "",
        "tags": [],
        "role_fit": [],
        "company_fit": [],
        "one_liner": "",
        "body": "",
    }


def test_render_round_trips_to_an_equal_document():
    doc = parse_story(SAMPLE)
    assert parse_story(render_story(SAMPLE, doc)) == doc


def test_render_keeps_a_frontmatter_key_the_form_does_not_model():
    text = "---\ntitle: T\nsource: linkedin\n---\n\nBody.\n"
    out = render_story(text, {"title": "New", "body": "Body."})
    assert "source: linkedin" in out
    assert "title: New" in out


def test_render_keeps_a_comment_in_the_frontmatter():
    text = "---\n# hands off\ntitle: T\n---\n\nBody.\n"
    assert "# hands off" in render_story(text, {"title": "New", "body": "Body."})


def test_render_replaces_only_the_keys_it_is_given():
    out = render_story(SAMPLE, {"tags": ["sre"]})
    doc = parse_story(out)
    assert doc["tags"] == ["sre"]
    assert doc["title"] == "Monitoring dashboard"
    assert doc["body"].startswith("**Context**")


def test_render_starts_a_file_that_had_no_frontmatter():
    out = render_story("Just prose.\n", {"tags": ["sre"], "body": "Just prose."})
    assert out.startswith("---\n")
    assert parse_story(out)["tags"] == ["sre"]
    assert parse_story(out)["body"] == "Just prose."


def test_render_keeps_markdown_in_the_body_verbatim():
    body = "**Context**: a --- inside the body, and a: colon.\n\n- a bullet"
    out = render_story(SAMPLE, {"body": body})
    assert parse_story(out)["body"] == body
