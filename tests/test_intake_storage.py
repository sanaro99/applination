"""Writing raw captured material to the _intake tree.

Slugs come from user-supplied titles, so containment is a security property
here, not a tidiness one.
"""
from __future__ import annotations

import pytest

from server.intake import (
    list_drafts,
    park_resume,
    read_notes,
    read_parked_resume,
    save_draft_story,
    save_notes,
    slugify,
)
from server.user_paths import PathEscape, UserPaths, resolve_within


@pytest.fixture()
def paths():
    return UserPaths(user_id=1).ensure()


def test_notes_round_trip(paths):
    save_notes(paths, "I mostly do backend work.")
    assert read_notes(paths) == "I mostly do backend work."


def test_reading_absent_notes_returns_empty_string(paths):
    assert read_notes(paths) == ""


def test_parked_resume_round_trip(paths):
    park_resume(paths, "Jane Doe\nSenior Engineer")
    assert "Senior Engineer" in read_parked_resume(paths)


def test_draft_story_is_written_with_frontmatter(paths):
    path = save_draft_story(paths, "The payments migration", "It was messy.")
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "draft: true" in text
    assert "It was messy." in text


def test_draft_story_keeps_the_body_verbatim(paths):
    body = "we shipped it   on a Friday\n\nwhich was a mistake"
    path = save_draft_story(paths, "Friday", body)
    assert body in path.read_text(encoding="utf-8")


def test_draft_lands_outside_the_real_stories_dir(paths):
    save_draft_story(paths, "A draft", "body")
    real = [p for p in paths.stories_dir.glob("*.md") if not p.name.startswith("_")]
    assert real == []


def test_colliding_titles_do_not_overwrite(paths):
    first = save_draft_story(paths, "Same title", "first body")
    second = save_draft_story(paths, "Same title", "second body")
    assert first != second
    assert "first body" in first.read_text(encoding="utf-8")
    assert "second body" in second.read_text(encoding="utf-8")


def test_list_drafts_returns_what_was_saved(paths):
    save_draft_story(paths, "One", "first")
    save_draft_story(paths, "Two", "second")
    drafts = list_drafts(paths)
    assert {d["title"] for d in drafts} == {"One", "Two"}
    assert all(d["captured_at"] for d in drafts)


def test_list_drafts_on_empty_tree(paths):
    assert list_drafts(paths) == []


def test_slugify_neutralises_traversal_input():
    assert "/" not in slugify("../../etc/passwd")
    assert ".." not in slugify("../../etc/passwd")


def test_slugify_falls_back_when_nothing_survives():
    assert slugify("!!!") == "story"


def test_a_crafted_slug_cannot_escape_the_intake_dir(paths):
    with pytest.raises(PathEscape):
        resolve_within(paths.intake_stories_dir, "../../../evil.md")


def test_traversal_title_still_lands_inside_intake(paths):
    path = save_draft_story(paths, "../../etc/passwd", "body")
    assert path.is_relative_to(paths.intake_stories_dir)
