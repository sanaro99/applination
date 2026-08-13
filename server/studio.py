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

from .config_api import STORIES_DIR
from .auth import require_owner
from .deps import load_config

# Owner-only, wholesale. Every endpoint here reads or writes the single global
# master_data/ profile, using the global provider keys, which is not per-user until PR 3. Signup is open, so
# without this any account could read and rewrite the owner's profile at the owner's expense.
#
# Applied at the router rather than per-endpoint so a new endpoint added to this
# file is owner-gated by default rather than by remembering.
router = APIRouter(
    prefix="/api/master-data", tags=["studio"],
    dependencies=[Depends(require_owner)],
)
log = logging.getLogger("server.studio")

_KINDS = {"story", "bio", "resume"}


def _resolve_chain(provider: str | None):
    """Return a provider chain: a single explicit provider if requested, else
    the configured content_studio task chain (with fallbacks)."""
    cfg = load_config()
    llm = cfg["llm"]
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
def generate_story_endpoint(body: GenerateStoryBody) -> GeneratedStory:
    if not body.description.strip():
        raise HTTPException(400, "description is required")

    from src.content_studio import (
        generate_story,
        load_taxonomy,
        slugify,
        story_dict_to_markdown,
    )
    from src.reference_loader import load_stories

    taxonomy = load_taxonomy(STORIES_DIR)
    existing = [s.get("title", "") for s in load_stories(STORIES_DIR)]
    existing_slugs = {p.stem for p in STORIES_DIR.glob("*.md")}

    chain = _resolve_chain(body.provider)
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
def tweak_endpoint(body: TweakBody) -> dict:
    kind = body.kind.strip().lower()
    if kind not in _KINDS:
        raise HTTPException(400, f"unknown kind: {body.kind}")
    if not body.instruction.strip():
        raise HTTPException(400, "instruction is required")
    if not body.text.strip():
        raise HTTPException(400, "text is required")

    from src.content_studio import tweak_content
    from src.reference_loader import load_stories

    stories = load_stories(STORIES_DIR) if kind in ("resume", "bio") else None
    chain = _resolve_chain(body.provider)
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
