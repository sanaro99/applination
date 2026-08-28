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
import re
from functools import lru_cache
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException
from jsonschema import Draft202012Validator
from pydantic import BaseModel

from .auth import require_user
from .db import User
from .deps import paths_for
from .user_paths import GLOBAL_MASTER_DIR, UserPaths
from src.intake_extract import load_vocabulary_groups
from src.master_resume import FORM_KEYS, load_master, render_master
from src.schemas import MASTER_RESUME_SCHEMA
from src.story_doc import FRONTMATTER_KEYS, LIST_KEYS, parse_story, render_story

router = APIRouter(prefix="/api/master-data", tags=["master-data"])


class TextBody(BaseModel):
    text: str


class StructuredBody(BaseModel):
    data: dict


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


def _field_path(error) -> str:
    """Turn a jsonschema error path into something a person can act on.

    ``deque(['experience', 1, 'company'])`` becomes ``experience[1].company``.
    The raw validator message names a JSON pointer and a schema fragment, which
    is not usable by the audience this editor exists for.
    """
    parts: list[str] = []
    for step in error.absolute_path:
        if isinstance(step, int):
            if parts:
                parts[-1] = f"{parts[-1]}[{step}]"
            else:
                parts.append(f"[{step}]")
        else:
            parts.append(str(step))
    return ".".join(parts)


def _validation_detail(error) -> str:
    where = _field_path(error)
    if error.validator == "required":
        match = re.search(r"'([^']+)'", error.message)
        field = match.group(1) if match else "a required field"
        return f"{where}.{field} is required" if where else f"{field} is required"
    return f"{where or 'the document'}: {error.message}"


def _for_schema(payload: dict) -> dict:
    """A copy shaped the way MASTER_RESUME_SCHEMA expects.

    The schema wants ``skills`` as a {group, items} list because structured
    output is more reliable with fixed keys. Disk wants the mapping, because a
    person has to read it. Neither is wrong; they just answer to different
    readers, so the conversion lives here and nowhere else.
    """
    if not isinstance(payload.get("skills"), dict):
        return payload
    return {
        **payload,
        "skills": [
            {"group": group, "items": items}
            for group, items in payload["skills"].items()
        ],
    }


@router.put("/resume/structured")
def put_resume_structured(
    body: StructuredBody, user: User = Depends(require_user)
) -> dict:
    """Validate, then merge into the file the user already has.

    Validation runs before any write, so a rejected save leaves the previous
    resume exactly as it was. Only the keys present in ``data`` are replaced —
    ``render_master`` leaves the rest, including anything the schema does not
    model.
    """
    payload = {k: v for k, v in body.data.items() if k in FORM_KEYS}

    errors = sorted(
        Draft202012Validator(MASTER_RESUME_SCHEMA).iter_errors(_for_schema(payload)),
        key=lambda e: list(e.absolute_path),
    )
    if errors:
        raise HTTPException(400, "; ".join(_validation_detail(e) for e in errors[:3]))

    path = _paths(user).resume_path
    _write(path, render_master(_read(path), payload))
    return {"ok": True}


@lru_cache(maxsize=1)
def _taxonomy() -> list[dict]:
    """The committed tag taxonomy, grouped as ``_INDEX.md`` groups it.

    Global and read-only, so it is cached for the process: it is a committed
    file that only changes on deploy. Served rather than copied into the
    browser because the file says "expand as needed", and a second copy would
    go stale the first time somebody does.
    """
    index = GLOBAL_MASTER_DIR / "stories" / "_INDEX.md"
    if not index.exists():
        return []
    return [
        {"label": g.label, "field": g.field, "tags": g.tags}
        for g in load_vocabulary_groups(index.read_text(encoding="utf-8"))
    ]


@router.get("/story-taxonomy")
def get_story_taxonomy(user: User = Depends(require_user)) -> dict:
    return {"groups": _taxonomy()}


@router.get("/stories/{name}/structured")
def get_story_structured(name: str, user: User = Depends(require_user)) -> dict:
    """One story as frontmatter fields plus body.

    Tolerant like its resume sibling: a broken header still opens, because the
    body is the part the user cannot regenerate.
    """
    _check_story_name(name)
    p = _paths(user).stories_dir / f"{name}.md"
    if not p.exists():
        raise HTTPException(404, "story not found")
    return {"name": name, "data": parse_story(_read(p))}


def _story_errors(data: dict) -> list[str]:
    """Type errors only, named by field.

    Deliberately not ``STORY_SCHEMA``: that schema constrains what the *model*
    must produce (a body of at least 400 characters, at least three tags), and
    holding a person to it would refuse to save a story they were halfway
    through writing. What actually breaks a consumer is a type — ``_score``
    iterates ``tags``, and a bare string there iterates characters — so that is
    what is enforced.
    """
    errors: list[str] = []
    for key in FRONTMATTER_KEYS:
        if key not in data:
            continue
        value = data[key]
        if key in LIST_KEYS:
            if not isinstance(value, list) or any(
                not isinstance(v, str) for v in value
            ):
                errors.append(f"{key} must be a list of tags")
        elif not isinstance(value, str):
            errors.append(f"{key} must be text")
    if "body" in data and not isinstance(data["body"], str):
        errors.append("body must be text")
    return errors


@router.put("/stories/{name}/structured")
def put_story_structured(
    name: str, body: StructuredBody, user: User = Depends(require_user)
) -> dict:
    """Validate, then merge into the story the user already has.

    Off-taxonomy tags are accepted on purpose. ``_INDEX.md`` calls its own list
    "expand as needed", and a picker that refused anything outside it would be
    a cage; the editor marks such a tag instead, since it misses the +5
    role-category bonus in ``reference_loader._score``.
    """
    _check_story_name(name)
    errors = _story_errors(body.data)
    if errors:
        raise HTTPException(400, "; ".join(errors[:3]))

    p = _paths(user).stories_dir / f"{name}.md"
    _write(p, render_story(_read(p), body.data))
    return {"ok": True}
