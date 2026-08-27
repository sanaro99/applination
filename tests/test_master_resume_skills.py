"""One shape for master `skills`, enforced at both boundaries.

`resume.yaml` had two shapes in circulation: the mapping the committed template
ships, and the `{group, items}` list `MASTER_RESUME_SCHEMA` requires — which is
what the onboarding resume import wrote. Consumers that did a bare `.items()`
or `.values()` crashed on the second, which meant a user who onboarded by
uploading a resume could not complete a run or open Coach.

The mapping wins because it is what the template ships, what most consumers
already read, and what a human can actually hand-edit. The LLM schema keeps its
fixed-key list — structured output is more reliable that way — so the list is
folded into a mapping on write, and anything already on disk in the old shape is
folded on read.
"""
from __future__ import annotations

import yaml

from src.content_studio import _coerce_master_resume, master_resume_to_yaml
from src.main import user_profile_blurb
from src.master_resume import load_master, normalize_master, normalize_skills
from src.profile import derive_profile, profile_summary_block

# Exactly what content_studio.import_resume hands back for MASTER_RESUME_SCHEMA.
AI_IMPORTED = {
    "summary_options": ["Engineer"],
    "core_skills": ["Python"],
    "skills": [
        {"group": "languages", "items": ["Python", "SQL"]},
        {"group": "frameworks", "items": ["FastAPI"]},
    ],
    "experience": [
        {"company": "X", "role": "Software Engineer", "bullets_all": ["did a thing"]}
    ],
    "education": [{"school": "U", "degree": "BS CS"}],
}


def _written_then_read(data: dict) -> dict:
    """Round-trip through the real onboarding write path."""
    return yaml.safe_load(master_resume_to_yaml(_coerce_master_resume(data)))


# --- the write boundary -----------------------------------------------------


def test_an_ai_imported_resume_is_written_with_skills_as_a_mapping():
    master = _written_then_read(AI_IMPORTED)
    assert master["skills"] == {"languages": ["Python", "SQL"], "frameworks": ["FastAPI"]}


def test_group_order_from_the_model_is_preserved_on_the_way_out():
    """The model orders groups most-relevant first; a dict that reordered them
    would quietly demote the group it led with."""
    master = _written_then_read(AI_IMPORTED)
    assert list(master["skills"]) == ["languages", "frameworks"]


# --- the crash sites --------------------------------------------------------


def test_user_profile_blurb_survives_an_ai_imported_resume():
    """src/pipeline.py calls this on every run."""
    master = _written_then_read(AI_IMPORTED)
    blurb = user_profile_blurb(master, {"full_name": "A"})
    assert "Python" in blurb


def test_profile_summary_block_survives_an_ai_imported_resume():
    """tailor.py and server/coach_context.py both call this."""
    master = _written_then_read(AI_IMPORTED)
    assert "Python" in profile_summary_block(master)


def test_derive_profile_survives_an_ai_imported_resume():
    master = _written_then_read(AI_IMPORTED)
    assert derive_profile(master)["identity_titles"]


# --- the read boundary, for files already written in the old shape ----------


def test_a_resume_already_on_disk_in_the_list_shape_is_folded_on_load(tmp_path):
    path = tmp_path / "resume.yaml"
    path.write_text(yaml.safe_dump(AI_IMPORTED), encoding="utf-8")
    assert load_master(path)["skills"] == {
        "languages": ["Python", "SQL"],
        "frameworks": ["FastAPI"],
    }


def test_a_mapping_shaped_resume_is_left_exactly_as_it_is(tmp_path):
    hand_written = {
        "summary_options": ["Engineer"],
        "skills": {"languages": ["Python"], "data": ["SQL"]},
        "experience": [],
        "education": [],
    }
    path = tmp_path / "resume.yaml"
    path.write_text(yaml.safe_dump(hand_written), encoding="utf-8")
    assert load_master(path)["skills"] == {"languages": ["Python"], "data": ["SQL"]}


def test_a_missing_resume_loads_as_an_empty_dict_not_a_crash(tmp_path):
    assert load_master(tmp_path / "nope.yaml") == {}


def test_an_empty_resume_file_loads_as_an_empty_dict(tmp_path):
    path = tmp_path / "resume.yaml"
    path.write_text("", encoding="utf-8")
    assert load_master(path) == {}


# --- the normalizer's own edges --------------------------------------------


def test_skills_that_are_neither_shape_normalize_to_empty_rather_than_raising():
    """A hand-edited file can contain anything. Downstream consumers index this
    with .items(), so the one thing it must never be is a surprise type."""
    for junk in ("Python, SQL", 42, None, ["Python", "SQL"]):
        assert isinstance(normalize_skills(junk), dict)


def test_a_list_entry_missing_its_group_is_dropped_not_guessed():
    assert normalize_skills([{"items": ["Python"]}, {"group": "data", "items": ["SQL"]}]) == {
        "data": ["SQL"]
    }


def test_duplicate_groups_merge_instead_of_the_last_one_winning():
    """Losing half a user's skills silently is worse than an odd merge."""
    assert normalize_skills(
        [
            {"group": "languages", "items": ["Python"]},
            {"group": "languages", "items": ["SQL"]},
        ]
    ) == {"languages": ["Python", "SQL"]}


def test_normalize_master_leaves_every_other_key_alone():
    before = dict(AI_IMPORTED)
    after = normalize_master(before)
    assert after["experience"] == AI_IMPORTED["experience"]
    assert after["education"] == AI_IMPORTED["education"]
    assert after["summary_options"] == AI_IMPORTED["summary_options"]


def test_normalize_master_does_not_mutate_what_it_was_given():
    original = {"skills": [{"group": "languages", "items": ["Python"]}]}
    normalize_master(original)
    assert original["skills"] == [{"group": "languages", "items": ["Python"]}]
