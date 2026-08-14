"""Shared resource access for the server — all of it per-user.

Every function here takes the user whose data is being read or written. There is
no global config any more; ``data/users/<id>/config.yaml`` is the unit, and
``server/user_paths.py`` owns the layout.
"""
from __future__ import annotations
from pathlib import Path
from typing import Callable

import yaml

from .user_paths import ROOT, UserPaths, user_paths
from .user_secrets import extract_secrets, merge_secrets

# Kept for the handful of callers that legitimately want the repo root (log
# paths, the committed example config). Not a config location any more.
__all__ = [
    "ROOT",
    "load_config",
    "update_config",
    "update_llm_config",
    "output_root",
    "paths_for",
]

EXAMPLE_CONFIG_PATH = ROOT / "config.example.yaml"


def paths_for(user: object) -> UserPaths:
    """This user's paths, with the directory tree created and config seeded."""
    return user_paths(user).ensure()


def load_config(user: object) -> dict:
    """This user's config, re-read every time so UI edits take effect without a
    restart, with their stored API keys merged in.

    The merge is why nothing downstream needs to know secrets are encrypted:
    callers get a config that looks exactly like the old single-tenant one.
    """
    paths = paths_for(user)
    raw = yaml.safe_load(paths.config_path.read_text(encoding="utf-8")) or {}
    return merge_secrets(raw, paths.user_id)


def load_config_redacted(user: object) -> dict:
    """This user's config with **no** secrets merged — what is safe to hand
    back to a browser or write to a log."""
    paths = paths_for(user)
    return yaml.safe_load(paths.config_path.read_text(encoding="utf-8")) or {}


def update_config(user: object, mutator: Callable[[dict], None]) -> None:
    """Round-trip the user's config.yaml through ruamel so comments, formatting,
    and unrelated sections survive, applying ``mutator`` to the whole document.

    ``mutator`` receives the live ruamel root mapping (a CommentedMap) and edits
    it in place. Any secret-bearing field it sets is diverted into encrypted
    storage and blanked in the file before the write, so a caller can keep
    writing ``llm.deepseek.api_key`` without knowing where it actually lands.
    """
    from ruamel.yaml import YAML

    yamlrt = YAML()
    yamlrt.preserve_quotes = True
    paths = paths_for(user)
    data = yamlrt.load(paths.config_path.read_text(encoding="utf-8"))
    if data is None:
        data = {}
    mutator(data)
    extract_secrets(data, paths.user_id)
    with paths.config_path.open("w", encoding="utf-8") as f:
        yamlrt.dump(data, f)


def update_llm_config(user: object, mutator: Callable[[dict], None]) -> None:
    """Apply ``mutator`` to the ``llm`` mapping, preserving everything else."""
    def _wrap(data: dict) -> None:
        if "llm" not in data or data["llm"] is None:
            data["llm"] = {}
        mutator(data["llm"])

    update_config(user, _wrap)


def output_root(user: object) -> Path:
    """Where this user's generated documents go.

    Deliberately **not** cached. The old single-tenant version was
    ``@lru_cache(maxsize=1)``, which with more than one user would hand the
    second caller the first caller's directory — every document written to, and
    served from, the wrong account's tree. The read is one small YAML parse; it
    is not worth a cache that can only ever be wrong.
    """
    paths = paths_for(user)
    root = paths.resolve_output(load_config_redacted(user))
    root.mkdir(parents=True, exist_ok=True)
    return root
