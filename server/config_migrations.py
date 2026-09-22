"""One-time, lossless migrations for persisted per-user configuration.

User configuration lives on the host volume rather than in the image, so
changing ``config.example.yaml`` cannot update accounts that already exist.
Migrations in this module are deliberately narrow: they replace only retired
provider identifiers, preserve comments and unrelated user choices, and are
safe to run on every startup/request path.
"""
from __future__ import annotations

from pathlib import Path
import shutil


# Keep these exact substitutions together so a model-default refresh has one
# auditable migration path for existing accounts as well as new accounts.
MODEL_IDENTIFIER_MIGRATIONS: dict[str, str] = {
    "deepseek-v4-flash": "deepseek-flash",
    "gemini-2.5-flash": "gemini-3.8-flash",
    "open-mixtral-8x22b": "mistral-small-latest",
    "tencent/hy3-preview:free": "nex-agi/nex-n2.5-mini:free",
}

ROUTING_PRESET_VERSION = 2


def ensure_provider_blocks(config_path: Path) -> bool:
    """Add newly supported provider blocks without changing anyone's routing.

    User configuration is persisted on the host volume. A new provider must be
    added independently of the image's example config or the workflow editor
    cannot offer it to existing accounts. This is intentionally additive: it
    never selects a provider, changes a model, or touches keys.
    """
    from ruamel.yaml import YAML

    yamlrt = YAML()
    yamlrt.preserve_quotes = True
    document = yamlrt.load(config_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        return False
    llm = document.get("llm")
    if not isinstance(llm, dict) or "openai" in llm:
        return False

    llm["openai"] = {"api_key": "", "model": "gpt-5.6-luna"}
    with config_path.open("w", encoding="utf-8") as handle:
        yamlrt.dump(document, handle)
    return True


def migrate_routing_preset(config_path: Path) -> bool:
    """Apply the approved DeepSeek-first routing preset once per user config.

    This migration intentionally changes routing (unlike the identifier-only
    migration above), so it leaves a local pre-migration copy beside the config
    before modifying anything. API keys are already blank in persisted config
    files and remain untouched in encrypted ``UserSecret`` rows.
    """
    from ruamel.yaml import YAML

    yamlrt = YAML()
    yamlrt.preserve_quotes = True
    document = yamlrt.load(config_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        return False
    llm = document.get("llm")
    if not isinstance(llm, dict):
        return False
    # The public demo intentionally routes every task to its committed fixture
    # adapter. Replacing that route with a real provider would both break the
    # demo and risk spending credentials on anonymous traffic.
    if str(llm.get("primary") or "").strip().lower() == "demo":
        return False
    try:
        if int(llm.get("routing_preset_version", 0) or 0) >= ROUTING_PRESET_VERSION:
            return False
    except (TypeError, ValueError):
        pass

    backup = config_path.with_name("config.pre-deepseek-routing-v2.yaml")
    if not backup.exists():
        shutil.copy2(config_path, backup)

    llm.setdefault("deepseek", {})
    llm["deepseek"].setdefault("api_key", "")
    llm["deepseek"]["model"] = "deepseek-flash"
    llm.setdefault("groq", {})
    llm["groq"].setdefault("api_key", "")
    llm["groq"]["model"] = "openai/gpt-oss-120b"
    llm.setdefault("gemini", {})
    llm["gemini"].setdefault("api_key", "")
    llm["gemini"]["model"] = "gemini-3.8-flash"
    llm.setdefault("cloudflare", {})
    llm["cloudflare"].setdefault("api_token", "")
    llm["cloudflare"].setdefault("account_id", "")
    llm["cloudflare"]["model"] = "@cf/google/gemma-4-26b-a4b-it"

    llm["primary"] = "deepseek"
    llm["fallbacks"] = ["groq", "gemini", "cloudflare"]

    llm["tasks"] = {
        "ranking": {"thinking": "off"},
        "critique": {"thinking": "off"},
        "job_extraction": {"thinking": "off"},
        "relinefit": {"thinking": "off"},
        "tailoring": {"thinking": "on"},
        "tailoring_premium": {"thinking": "on"},
        "cover_letter": {"thinking": "on"},
        "answer_questions": {"thinking": "on"},
        "content_studio": {"thinking": "on"},
        "tweak": {"thinking": "on"},
        "coach": {"thinking": "on"},
        "interview": {"thinking": "on"},
        "essay": {"thinking": "on"},
    }
    llm["routing_preset_version"] = ROUTING_PRESET_VERSION
    with config_path.open("w", encoding="utf-8") as handle:
        yamlrt.dump(document, handle)
    return True


# Compatibility aliases for callers or deployments importing the v1 names.
FREE_POOL_ROUTING_VERSION = ROUTING_PRESET_VERSION
migrate_free_pool_routing = migrate_routing_preset


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
