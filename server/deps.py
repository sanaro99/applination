"""Shared resource access for the server."""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
from typing import Callable

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
EXAMPLE_CONFIG_PATH = ROOT / "config.example.yaml"


def _ensure_config() -> None:
    """Seed config.yaml from the committed template on first run so the app
    boots (and onboarding can run) before the user has set anything up."""
    if not CONFIG_PATH.exists() and EXAMPLE_CONFIG_PATH.exists():
        CONFIG_PATH.write_text(
            EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8"
        )


def load_config() -> dict:
    """Always re-read the config so UI edits take effect without a restart."""
    _ensure_config()
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}


def update_config(mutator: Callable[[dict], None]) -> None:
    """Round-trip config.yaml through ruamel so comments, formatting, and
    unrelated sections survive, applying ``mutator`` to the whole document.

    ``mutator`` receives the live ruamel root mapping (a CommentedMap) and
    edits it in place. Use this for structured edits (onboarding writes
    user/search/provider blocks) so comments are preserved.
    """
    from ruamel.yaml import YAML

    yamlrt = YAML()
    yamlrt.preserve_quotes = True
    _ensure_config()
    data = yamlrt.load(CONFIG_PATH.read_text(encoding="utf-8"))
    mutator(data)
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        yamlrt.dump(data, f)


def update_llm_config(mutator: Callable[[dict], None]) -> None:
    """Apply ``mutator`` to the ``llm`` mapping, preserving everything else."""
    def _wrap(data: dict) -> None:
        if "llm" not in data or data["llm"] is None:
            data["llm"] = {}
        mutator(data["llm"])

    update_config(_wrap)


@lru_cache(maxsize=1)
def output_root() -> Path:
    cfg = load_config()
    return Path(cfg["output"]["root"])
