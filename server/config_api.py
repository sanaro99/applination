"""Config + master-data editor endpoints — per-user.

Before PR 3 this router was owner-only, because every path it touched was the
one global ``config.yaml`` / ``master_data/``. Both are now per-account, so
every endpoint here is plain ``require_user`` again and resolves through
``UserPaths``. There is no global file left for one account to reach.

Secrets never make the round trip: ``PUT /api/config`` diverts API keys into
encrypted storage and blanks them in the file, so the ``GET`` that follows
returns a document with the fields present but empty. ``GET /api/secrets``
reports which ones are actually set.
"""
from __future__ import annotations
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import require_user
from .db import User
from .deps import load_config, paths_for, update_config
from .user_secrets import extract_secrets, secrets_status

router = APIRouter(prefix="/api", tags=["config"])


class TextBody(BaseModel):
    text: str


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@router.get("/config")
def get_config(user: User = Depends(require_user)) -> dict:
    return {"text": _read(paths_for(user).config_path)}


@router.put("/config")
def put_config(body: TextBody, user: User = Depends(require_user)) -> dict:
    """Save the raw YAML, diverting any secrets it contains.

    The saved text is not byte-identical to what was submitted when it carried a
    key: the value is stored encrypted and written back as ``""``. That is
    visible to the user on the next load, which is the intended behaviour —
    silently keeping the key in the file would be the surprise.
    """
    try:
        parsed = yaml.safe_load(body.text)
    except yaml.YAMLError as e:
        raise HTTPException(400, f"invalid YAML: {e}") from e
    if parsed is not None and not isinstance(parsed, dict):
        raise HTTPException(400, "config must be a YAML mapping")

    paths = paths_for(user)
    text = body.text
    # Only pay the ruamel round trip when there is actually a secret to divert,
    # so an ordinary edit is saved exactly as typed.
    if parsed:
        from ruamel.yaml import YAML

        yamlrt = YAML()
        yamlrt.preserve_quotes = True
        doc = yamlrt.load(body.text)
        if doc is not None and extract_secrets(doc, paths.user_id):
            import io

            buf = io.StringIO()
            yamlrt.dump(doc, buf)
            text = buf.getvalue()

    _write(paths.config_path, text)
    return {"ok": True}


class KeywordsBody(BaseModel):
    keywords: list[str]


@router.get("/search/keywords")
def get_search_keywords(user: User = Depends(require_user)) -> dict:
    """The target-roles list only (`search.keywords`), for the Master Data
    'Target roles' tab. Kept separate from /api/onboarding/search, which also
    writes remote_ok/onsite_cities/countries — this endpoint must not touch
    those when a user only edits their roles after onboarding."""
    cfg = load_config(user) or {}
    keywords = (cfg.get("search") or {}).get("keywords") or []
    return {"keywords": [str(k) for k in keywords]}


@router.put("/search/keywords")
def put_search_keywords(body: KeywordsBody, user: User = Depends(require_user)) -> dict:
    def mut(data: dict) -> None:
        search = data.get("search")
        if search is None:
            search = {}
            data["search"] = search
        search["keywords"] = [k.strip() for k in body.keywords if k.strip()]
    update_config(user, mut)
    return {"ok": True}


@router.get("/secrets")
def get_secrets(user: User = Depends(require_user)) -> dict:
    """Which API keys are stored, masked. Never returns a usable credential."""
    return secrets_status(user.id)  # type: ignore[arg-type]
