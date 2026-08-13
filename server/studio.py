"""LLM-assisted master-data authoring endpoints.

Generate a new story from a description, or tweak an existing story / bio /
resume by instruction. Both return a PREVIEW only — saving reuses the existing
PUT /api/master-data/* endpoints in config_api.py.
"""
from __future__ import annotations

import logging

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import require_user
from .db import User
from .deps import load_config, paths_for

# Per-user as of PR 3: each account reads and rewrites its own master_data/
# profile, paid for with its own provider keys. (PR 2 had this owner-only,
# because both the profile and the keys were a single global.)
router = APIRouter(prefix="/api/master-data", tags=["studio"])
log = logging.getLogger("server.studio")

_KINDS = {"story", "bio", "resume"}


def _resolve_chain(user: User, provider: str | None):
    """Return a provider chain: a single explicit provider if requested, else
    the configured content_studio task chain (with fallbacks)."""
    cfg = load_config(user)
    llm = cfg.get("llm") or {}
    if provider:
        from src.providers import get_provider
        name = provider.strip().lower()
        try:
            return [get_provider(name, llm)]
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"could not build provider '{name}': {e}")
    from src.providers import get_provider_chain, get_task_chains
    try:
        chain = get_task_chains(llm).get("content_studio")
    except Exception:  # noqa: BLE001
        chain = None
    return chain or get_provider_chain(llm)


def _call(chain, fn):
    from src.providers import try_chain
    if not chain:
        raise HTTPException(502, "no LLM provider is configured")
    try:
        return try_chain(chain, fn, any_error=True, task_name="content_studio")
    except Exception as e:  # noqa: BLE001
        log.exception("content studio call failed: %s", e)
        raise HTTPException(502, f"generation failed: {e}") from e


class GenerateStoryBody(BaseModel):
    description: str
    provider: str | None = None


class GeneratedStory(BaseModel):
    filename: str
    text: str
    fields: dict


@router.post("/stories/generate", response_model=GeneratedStory)
def generate_story_endpoint(
    body: GenerateStoryBody, user: User = Depends(require_user)
) -> GeneratedStory:
    if not body.description.strip():
        raise HTTPException(400, "description is required")

    from src.content_studio import (
        generate_story,
        load_taxonomy,
        slugify,
        story_dict_to_markdown,
    )
    from src.reference_loader import load_stories

    paths = paths_for(user)
    stories_dir = paths.stories_dir
    # Taxonomy from the committed global _INDEX.md, stories from the user's own
    # directory — the vocabulary is shared, the content is not.
    taxonomy = load_taxonomy(paths.taxonomy_dir)
    existing = [s.get("title", "") for s in load_stories(stories_dir)]
    existing_slugs = {p.stem for p in stories_dir.glob("*.md")}

    chain = _resolve_chain(user, body.provider)
    story = _call(
        chain,
        lambda p: generate_story(
            body.description, provider=p, taxonomy=taxonomy,
            existing_titles=existing,
        ),
    )
    text = story_dict_to_markdown(story)
    # Unique slug so generating twice doesn't propose an overwrite.
    base = slugify(story.get("title", "story"))
    slug, i = base, 2
    while slug in existing_slugs:
        slug = f"{base}-{i}"
        i += 1
    return GeneratedStory(filename=slug, text=text, fields=story)


class TweakBody(BaseModel):
    kind: str
    text: str
    instruction: str
    provider: str | None = None


@router.post("/tweak")
def tweak_endpoint(body: TweakBody, user: User = Depends(require_user)) -> dict:
    kind = body.kind.strip().lower()
    if kind not in _KINDS:
        raise HTTPException(400, f"unknown kind: {body.kind}")
    if not body.instruction.strip():
        raise HTTPException(400, "instruction is required")
    if not body.text.strip():
        raise HTTPException(400, "text is required")

    from src.content_studio import tweak_content
    from src.reference_loader import load_stories

    stories = (
        load_stories(paths_for(user).stories_dir)
        if kind in ("resume", "bio")
        else None
    )
    chain = _resolve_chain(user, body.provider)
    text = _call(
        chain,
        lambda p: tweak_content(
            kind, body.text, body.instruction, provider=p, stories=stories
        ),
    )
    # Guard structured formats so we never hand back unparseable content.
    if kind in ("resume",):
        try:
            yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise HTTPException(502, f"model returned invalid YAML: {e}") from e
    if kind == "story":
        _validate_story_frontmatter(text)
    return {"text": text}


def _validate_story_frontmatter(text: str) -> None:
    t = text.lstrip()
    if not t.startswith("---"):
        raise HTTPException(502, "model dropped the story frontmatter")
    try:
        _, fm, _ = t.split("---", 2)
        yaml.safe_load(fm)
    except (ValueError, yaml.YAMLError) as e:
        raise HTTPException(502, f"invalid story frontmatter: {e}") from e
