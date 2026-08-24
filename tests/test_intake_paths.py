"""The _intake tree: where raw captured material lives before enrichment.

It sits under master_data/ but outside stories/, because reference_loader and
onboarding._count_stories glob stories/*.md — a draft landing there would be
matched into a real cover letter.
"""
from __future__ import annotations

from server.user_paths import UserPaths


def test_ensure_creates_the_intake_tree():
    paths = UserPaths(user_id=1).ensure()
    assert paths.intake_dir.is_dir()
    assert paths.intake_stories_dir.is_dir()
    assert paths.intake_consumed_dir.is_dir()


def test_ensure_is_idempotent():
    UserPaths(user_id=1).ensure()
    paths = UserPaths(user_id=1).ensure()
    assert paths.intake_stories_dir.is_dir()


def test_intake_files_sit_inside_intake_dir():
    paths = UserPaths(user_id=1)
    assert paths.intake_resume_path.parent == paths.intake_dir
    assert paths.intake_notes_path.parent == paths.intake_dir


def test_drafts_are_invisible_to_the_real_stories_glob():
    paths = UserPaths(user_id=1).ensure()
    (paths.intake_stories_dir / "a-draft.md").write_text("draft", encoding="utf-8")
    real = [p for p in paths.stories_dir.glob("*.md") if not p.name.startswith("_")]
    assert real == []
