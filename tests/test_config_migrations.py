"""Regression coverage for model-name migrations on the persisted config volume."""
from __future__ import annotations

import yaml

from server.config_migrations import (
    FREE_POOL_ROUTING_VERSION,
    ensure_provider_blocks,
    migrate_free_pool_routing,
    migrate_legacy_model_identifiers,
)
from server.user_paths import UserPaths


def test_ensure_provider_blocks_is_additive_and_idempotent(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("llm:\n  primary: gemini\n  gemini:\n    model: gemini-3.8-flash\n")

    assert ensure_provider_blocks(config) is True
    assert ensure_provider_blocks(config) is False

    saved = yaml.safe_load(config.read_text())
    assert saved["llm"]["primary"] == "gemini"
    assert saved["llm"]["openai"] == {
        "api_key": "", "model": "gpt-5.6-luna",
    }


def test_retired_model_ids_migrate_in_provider_blocks_and_task_overrides(tmp_path, monkeypatch):
    from server import user_paths

    monkeypatch.setattr(user_paths, "USERS_DIR", tmp_path / "users")
    path = UserPaths(user_id=7).ensure().config_path
    path.write_text(
        """# Keep this comment.\nllm:\n  deepseek:\n    model: deepseek-v4-flash\n  gemini:\n    model: gemini-2.5-flash\n  mistral:\n    model: open-mixtral-8x22b\n  openrouter:\n    model: tencent/hy3-preview:free\n  tasks:\n    tailoring:\n      models:\n        deepseek: deepseek-v4-flash\n        openrouter: tencent/hy3-preview:free\n""",
        encoding="utf-8",
    )

    changed = migrate_legacy_model_identifiers(path)
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert len(changed) == 6
    assert saved["llm"]["deepseek"]["model"] == "deepseek-flash"
    assert saved["llm"]["gemini"]["model"] == "gemini-3.8-flash"
    assert saved["llm"]["mistral"]["model"] == "mistral-small-latest"
    assert saved["llm"]["openrouter"]["model"] == "nex-agi/nex-n2.5-mini:free"
    assert saved["llm"]["tasks"]["tailoring"]["models"] == {
        "deepseek": "deepseek-flash",
        "openrouter": "nex-agi/nex-n2.5-mini:free",
    }
    assert "# Keep this comment." in path.read_text(encoding="utf-8")
    assert migrate_legacy_model_identifiers(path) == []


def test_user_paths_runs_the_migration_for_an_existing_config(tmp_path, monkeypatch):
    from server import user_paths

    monkeypatch.setattr(user_paths, "USERS_DIR", tmp_path / "users")
    path = UserPaths(user_id=8).ensure().config_path
    path.write_text("llm:\n  deepseek:\n    model: deepseek-v4-flash\n", encoding="utf-8")

    UserPaths(user_id=8).ensure()

    assert yaml.safe_load(path.read_text(encoding="utf-8"))["llm"]["deepseek"]["model"] == "deepseek-flash"


def test_free_pool_routing_migration_keeps_a_local_rollback_copy(tmp_path):
    path = tmp_path / "config.yaml"
    original = "# personal comment\nllm:\n  primary: deepseek\n  deepseek:\n    model: deepseek-flash\n"
    path.write_text(original, encoding="utf-8")

    assert migrate_free_pool_routing(path) is True
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert (tmp_path / "config.pre-free-routing-v1.yaml").read_text(encoding="utf-8") == original
    assert saved["llm"]["routing_preset_version"] == FREE_POOL_ROUTING_VERSION
    assert saved["llm"]["tasks"]["ranking"]["primary"] == "groq"
    assert saved["llm"]["tasks"]["tailoring"]["primary"] == "nim"
    assert migrate_free_pool_routing(path) is False
