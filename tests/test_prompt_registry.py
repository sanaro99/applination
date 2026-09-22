from __future__ import annotations

import pytest

from src.prompt_registry import PROMPTS, editorial_prompt_manifest


def test_registered_prompt_builds_safe_reproducibility_metadata():
    prompt = PROMPTS.build(
        "resume.content_plan",
        system="stable instructions",
        user="private candidate material",
        schema={"type": "object"},
    )

    metadata = prompt.metadata()
    assert metadata["id"] == "resume.content_plan@1"
    assert metadata["version"] == "1"
    assert len(metadata["rendered_sha256"]) == 64
    assert "private candidate material" not in str(metadata)


def test_rendered_hash_changes_when_prompt_content_changes():
    first = PROMPTS.build(
        "resume.editorial_write", system="one", user="input",
    )
    second = PROMPTS.build(
        "resume.editorial_write", system="two", user="input",
    )
    assert first.rendered_sha256 != second.rendered_sha256


def test_manifest_is_version_only_and_unknown_versions_fail():
    manifest = editorial_prompt_manifest()
    assert manifest["cover_letter.write"] == "1"
    assert all(isinstance(version, str) for version in manifest.values())

    with pytest.raises(ValueError, match="has version"):
        PROMPTS.build(
            "cover_letter.write", system="system", user="user", version="2",
        )
