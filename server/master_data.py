"""Master-data endpoints — per-user, file-backed.

Split out of ``config_api.py``, which was serving two unrelated resources.
The URLs are unchanged. Nothing here touches a DB table: every path resolves
through ``paths_for(user)``, so ``server/scoping.py`` does not apply.

The text endpoints are deliberately permissive — they only check that the input
parses as YAML — because they back the Advanced editor, which is the escape
hatch for anything the structured schema does not model. The structured
endpoints in this same file are strict. Tolerant on read, strict on write.
"""
from __future__ import annotations
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import require_user
from .db import User
from .deps import paths_for
from .user_paths import UserPaths
from src.master_resume import load_master

router = APIRouter(prefix="/api/master-data", tags=["master-data"])


class TextBody(BaseModel):
    text: str


def _paths(user: User) -> UserPaths:
    return paths_for(user)


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _check_story_name(name: str) -> None:
    """Reject anything that could leave the user's stories directory.

    ``paths.ensure()`` creates the directory, but nothing else stops
    ``../../2/master_data`` from being appended to it.
    """
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(400, "invalid story name")


@router.get("/resume")
def get_resume(user: User = Depends(require_user)) -> dict:
    return {"text": _read(_paths(user).resume_path)}


@router.put("/resume")
def put_resume(body: TextBody, user: User = Depends(require_user)) -> dict:
    try:
        yaml.safe_load(body.text)
    except yaml.YAMLError as e:
        raise HTTPException(400, f"invalid YAML: {e}") from e
    _write(_paths(user).resume_path, body.text)
    return {"ok": True}


@router.get("/bio")
def get_bio(user: User = Depends(require_user)) -> dict:
    return {"text": _read(_paths(user).bio_path)}


@router.put("/bio")
def put_bio(body: TextBody, user: User = Depends(require_user)) -> dict:
    _write(_paths(user).bio_path, body.text)
    return {"ok": True}


@router.get("/stories")
def list_stories(user: User = Depends(require_user)) -> list[dict]:
    stories_dir = _paths(user).stories_dir
    if not stories_dir.exists():
        return []
    out: list[dict] = []
    for p in sorted(stories_dir.glob("*.md")):
        if p.name.startswith("_"):
            continue
        out.append({"name": p.stem, "size": p.stat().st_size})
    return out


@router.get("/stories/{name}")
def get_story(name: str, user: User = Depends(require_user)) -> dict:
    _check_story_name(name)
    p = _paths(user).stories_dir / f"{name}.md"
    if not p.exists():
        raise HTTPException(404, "story not found")
    return {"name": name, "text": _read(p)}


@router.put("/stories/{name}")
def put_story(name: str, body: TextBody, user: User = Depends(require_user)) -> dict:
    _check_story_name(name)
    _write(_paths(user).stories_dir / f"{name}.md", body.text)
    return {"ok": True}


@router.get("/resume/structured")
def get_resume_structured(user: User = Depends(require_user)) -> dict:
    """The resume as a dict, normalized.

    Tolerant by design: a half-finished or slightly wrong file still loads, so
    the form can render what is there instead of refusing to open. Strictness
    belongs on the way out, in PUT.
    """
    return {"data": load_master(_paths(user).resume_path)}
