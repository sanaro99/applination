"""Saving the master resume must not damage what it did not touch.

The form owns eight top-level keys. Everything else in the file — comments a
user added through the Advanced tab, keys the schema does not model, the order
things appear in — belongs to the user, and a save that quietly discards any of
it is data loss in a file holding someone's career history.
"""
from __future__ import annotations

import yaml

from src.master_resume import FORM_KEYS, render_master

COMMENTED = """\
# My master resume. Notes to self below.
summary_options:
  - "Engineer"          # the one I actually use
core_skills:
  - "Python"
# Everything under here is mine, hands off.
private_notes: "call recruiter back"
"""


def test_the_eight_form_keys_are_exactly_what_the_form_owns():
    assert FORM_KEYS == (
        "profile",
        "summary_options",
        "core_skills",
        "ats_adjacent_skills",
        "skills",
        "experience",
        "projects",
        "education",
    )


def test_a_replaced_key_takes_the_new_value():
    out = render_master(COMMENTED, {"core_skills": ["Python", "Go"]})
    assert yaml.safe_load(out)["core_skills"] == ["Python", "Go"]


def test_comments_survive_a_save():
    out = render_master(COMMENTED, {"core_skills": ["Go"]})
    assert "# My master resume. Notes to self below." in out
    assert "# Everything under here is mine, hands off." in out


def test_a_key_the_schema_does_not_model_survives_a_save():
    out = render_master(COMMENTED, {"core_skills": ["Go"]})
    assert yaml.safe_load(out)["private_notes"] == "call recruiter back"


def test_a_key_absent_from_the_payload_is_left_alone_not_deleted():
    """The form renders a section at a time; omitting one must not erase it."""
    out = render_master(COMMENTED, {"core_skills": ["Go"]})
    assert yaml.safe_load(out)["summary_options"] == ["Engineer"]


def test_key_order_is_preserved():
    out = render_master(COMMENTED, {"core_skills": ["Go"]})
    assert list(yaml.safe_load(out)) == [
        "summary_options",
        "core_skills",
        "private_notes",
    ]


def test_skills_are_normalized_on_the_way_in():
    """A client that sends the old list shape must not put it back on disk."""
    out = render_master(
        "", {"skills": [{"group": "languages", "items": ["Python"]}]}
    )
    assert yaml.safe_load(out)["skills"] == {"languages": ["Python"]}


def test_an_empty_file_renders_a_whole_document():
    out = render_master("", {"core_skills": ["Python"]})
    assert yaml.safe_load(out) == {"core_skills": ["Python"]}


def test_a_long_bullet_is_not_rewrapped():
    """Rewrapping turns one bullet into a multi-line scalar, which shows up as a
    spurious change the next time the diff runs."""
    bullet = "Built " + "a very long thing " * 12
    out = render_master(
        "", {"experience": [{"company": "X", "role": "Y", "bullets_all": [bullet]}]}
    )
    assert yaml.safe_load(out)["experience"][0]["bullets_all"] == [bullet]
    assert bullet.strip() in out.replace("\n", " ")
