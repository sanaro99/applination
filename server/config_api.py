"""Config + master-data editor endpoints."""
from __future__ import annotations
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import require_owner
from .deps import CONFIG_PATH, ROOT

# Owner-only, wholesale. Every endpoint here reads or writes the single global
# config.yaml and master_data/, which is not per-user until PR 3. Signup is open, so
# without this any account could read the owner's API keys and personal resume.
#
# Applied at the router rather than per-endpoint so a new endpoint added to this
# file is owner-gated by default rather than by remembering.
router = APIRouter(
    prefix="/api", tags=["config"],
    dependencies=[Depends(require_owner)],
)

MASTER_DIR = ROOT / "master_data"
STORIES_DIR = MASTER_DIR / "stories"
BIO_PATH = MASTER_DIR / "bio.md"
RESUME_PATH = MASTER_DIR / "resume.yaml"


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
def get_config() -> dict:
    return {"text": _read(CONFIG_PATH)}


@router.put("/config")
def put_config(body: TextBody) -> dict:
    try:
        yaml.safe_load(body.text)
    except yaml.YAMLError as e:
        raise HTTPException(400, f"invalid YAML: {e}") from e
    _write(CONFIG_PATH, body.text)
    return {"ok": True}


@router.get("/master-data/resume")
def get_resume() -> dict:
    return {"text": _read(RESUME_PATH)}


@router.put("/master-data/resume")
def put_resume(body: TextBody) -> dict:
    try:
        yaml.safe_load(body.text)
    except yaml.YAMLError as e:
        raise HTTPException(400, f"invalid YAML: {e}") from e
    _write(RESUME_PATH, body.text)
    return {"ok": True}


@router.get("/master-data/bio")
def get_bio() -> dict:
    return {"text": _read(BIO_PATH)}


@router.put("/master-data/bio")
def put_bio(body: TextBody) -> dict:
    _write(BIO_PATH, body.text)
    return {"ok": True}


@router.get("/master-data/stories")
def list_stories() -> list[dict]:
    if not STORIES_DIR.exists():
        return []
    out: list[dict] = []
    for p in sorted(STORIES_DIR.glob("*.md")):
        if p.name.startswith("_"):
            continue
        out.append({"name": p.stem, "size": p.stat().st_size})
    return out


@router.get("/master-data/stories/{name}")
def get_story(name: str) -> dict:
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(400, "invalid story name")
    p = STORIES_DIR / f"{name}.md"
    if not p.exists():
        raise HTTPException(404, "story not found")
    return {"name": name, "text": _read(p)}


@router.put("/master-data/stories/{name}")
def put_story(name: str, body: TextBody) -> dict:
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(400, "invalid story name")
    _write(STORIES_DIR / f"{name}.md", body.text)
    return {"ok": True}
