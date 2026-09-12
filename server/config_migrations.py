"""One-time, lossless migrations for persisted per-user configuration.

User configuration lives on the host volume rather than in the image, so
changing ``config.example.yaml`` cannot update accounts that already exist.
Migrations in this module are deliberately narrow: they replace only retired
provider identifiers, preserve comments and unrelated user choices, and are
safe to run on every startup/request path.
"""
from __future__ import annotations

from pathlib import Path


# Keep these exact substitutions together so a model-default refresh has one
# auditable migration path for existing accounts as well as new accounts.
MODEL_IDENTIFIER_MIGRATIONS: dict[str, str] = {
    "deepseek-v4-flash": "deepseek-flash",
    "gemini-2.5-flash": "gemini-3.8-flash",
    "open-mixtral-8x22b": "mistral-small-latest",
    "tencent/hy3-preview:free": "nex-agi/nex-n2.5-mini:free",
}


def migrate_legacy_model_identifiers(config_path: Path) -> list[tuple[str, str]]:
    """Replace retired model IDs in one persisted config file.

    The file can contain personal information, so this function never logs its
    contents.  ``ruamel`` keeps its comments and key order intact; an unchanged
    file is never rewritten.
    """
    from ruamel.yaml import YAML

    yamlrt = YAML()
    yamlrt.preserve_quotes = True
    document = yamlrt.load(config_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        return []

    llm = document.get("llm")
    if not isinstance(llm, dict):
        return []

    changes: list[tuple[str, str]] = []

    # Provider blocks are what the Config page displays.
    for block in llm.values():
        if not isinstance(block, dict):
            continue
        model = block.get("model")
        replacement = MODEL_IDENTIFIER_MIGRATIONS.get(str(model))
        if replacement:
            block["model"] = replacement
            changes.append((str(model), replacement))

    # Per-workflow overrides are stored separately and must not be left behind.
    tasks = llm.get("tasks")
    if isinstance(tasks, dict):
        for task in tasks.values():
            models = task.get("models") if isinstance(task, dict) else None
            if not isinstance(models, dict):
                continue
            for provider, model in models.items():
                replacement = MODEL_IDENTIFIER_MIGRATIONS.get(str(model))
                if replacement:
                    models[provider] = replacement
                    changes.append((str(model), replacement))

    if changes:
        with config_path.open("w", encoding="utf-8") as handle:
            yamlrt.dump(document, handle)
    return changes
