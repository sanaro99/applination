"""Turn captured raw material into real master data, one step at a time.

The journey deliberately runs before the user has an API key, so every AI
transformation lands here instead of inline at capture time. That separation
also means capture never fails because a model was down, a key was wrong or a
quota was hit — and each step below is independently retryable.

The client drives the steps one at a time so that the profile meter fills
against real state rather than a timed fake, and so a single failure is
retryable in place without restarting the cascade.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException

from src.content_studio import (
    generate_story,
    import_resume,
    load_taxonomy,
    master_resume_to_yaml,
    story_dict_to_markdown,
    suggest_keywords,
    tweak_content,
)

from . import intake as intake_store
from .db import User
from .deps import paths_for
from .intake import slugify
from .studio import _call, _resolve_chain

log = logging.getLogger("server.enrichment")


def plan(user: User) -> list[dict]:
    """Ordered, pending enrichment steps.

    A step appears only when its input exists and its output does not, which is
    what makes the whole cascade idempotent: re-running it after a partial
    failure simply produces a shorter plan.
    """
    paths = paths_for(user)
    steps: list[dict] = []

    parked = intake_store.read_parked_resume(paths).strip()
    if parked and not paths.resume_path.exists():
        steps.append(
            {"id": "resume", "label": "Reading your resume", "part": "resume"}
        )

    drafts = intake_store.list_drafts(paths)
    for index, draft in enumerate(drafts, start=1):
        steps.append(
            {
                "id": f"story:{draft['slug']}",
                "label": f"Shaping “{draft['title']}”",
                "part": f"story_{min(index, 3)}",
            }
        )

    notes = intake_store.read_notes(paths).strip()
    if notes and not paths.bio_path.exists():
        steps.append({"id": "bio", "label": "Learning your voice", "part": "voice"})

    if parked or notes or drafts:
        steps.append(
            {"id": "search", "label": "Working out what to look for", "part": "search"}
        )

    return steps


def _existing_titles(paths) -> list[str]:
    from src.reference_loader import load_stories

    if not paths.stories_dir.exists():
        return []
    return [str(s.get("title") or "") for s in load_stories(paths.stories_dir)]


def _consume_draft(paths, slug: str) -> None:
    """Move a used draft aside instead of deleting it.

    The draft is the user's own words. If enrichment produced something they
    dislike, the raw material has to still be there.
    """
    source = paths.intake_stories_dir / f"{slug}.md"
    if not source.exists():
        return
    paths.intake_consumed_dir.mkdir(parents=True, exist_ok=True)
    target = paths.intake_consumed_dir / source.name
    counter = 2
    while target.exists():
        target = paths.intake_consumed_dir / f"{source.stem}-{counter}.md"
        counter += 1
    source.replace(target)


def run_step(user: User, step_id: str, *, force: bool = False) -> dict:
    """Run one enrichment step. Idempotent unless ``force``."""
    paths = paths_for(user)
    chain = _resolve_chain(user, None)

    if step_id == "resume":
        if paths.resume_path.exists() and not force:
            return {"id": step_id, "done": True, "skipped": True, "part": "resume", "result": None}
        parked = intake_store.read_parked_resume(paths).strip()
        if not parked:
            raise HTTPException(404, "no parked resume to import")
        data = _call(chain, lambda p: import_resume(parked, provider=p))
        paths.resume_path.write_text(master_resume_to_yaml(data), encoding="utf-8")
        return {"id": step_id, "done": True, "skipped": False, "part": "resume", "result": None}

    if step_id.startswith("story:"):
        slug = step_id.split(":", 1)[1]
        draft = next(
            (d for d in intake_store.list_drafts(paths) if d["slug"] == slug), None
        )
        if draft is None:
            raise HTTPException(404, f"no draft story '{slug}'")
        taxonomy = load_taxonomy(paths.taxonomy_dir)
        story = _call(
            chain,
            lambda p: generate_story(
                draft["body"],
                provider=p,
                taxonomy=taxonomy,
                existing_titles=_existing_titles(paths),
            ),
        )
        name = slugify(str(story.get("title") or draft["title"]))
        target = paths.stories_dir / f"{name}.md"
        counter = 2
        while target.exists():
            target = paths.stories_dir / f"{name}-{counter}.md"
            counter += 1
        target.write_text(story_dict_to_markdown(story), encoding="utf-8")
        _consume_draft(paths, slug)
        return {
            "id": step_id,
            "done": True,
            "skipped": False,
            "part": "story_1",
            "result": {"title": story.get("title"), "file": target.name},
        }

    if step_id == "bio":
        if paths.bio_path.exists() and not force:
            return {"id": step_id, "done": True, "skipped": True, "part": "voice", "result": None}
        notes = intake_store.read_notes(paths).strip()
        if not notes:
            raise HTTPException(404, "no notes to derive a voice from")
        text = _call(
            chain,
            lambda p: tweak_content(
                "bio",
                notes,
                "Turn this into a short voice guide describing how this person "
                "writes and what they care about. Keep their own words and "
                "specifics wherever possible. Invent nothing.",
                provider=p,
            ),
        )
        paths.bio_path.write_text(text, encoding="utf-8")
        return {"id": step_id, "done": True, "skipped": False, "part": "voice", "result": None}

    if step_id == "search":
        told = intake_store.read_notes(paths)
        drafts = intake_store.list_drafts(paths)
        corpus = "\n\n".join(
            [told, *(d["body"] for d in drafts), intake_store.read_parked_resume(paths)]
        ).strip()
        if not corpus:
            raise HTTPException(404, "nothing captured to work from")
        keywords = _call(chain, lambda p: suggest_keywords(corpus, provider=p))
        # Proposes only. The user's chips are theirs; writing config here would
        # overwrite a correction they already made in chapter 4.
        return {
            "id": step_id,
            "done": True,
            "skipped": False,
            "part": "search",
            "result": {"keywords": keywords},
        }

    raise HTTPException(400, f"unknown enrichment step '{step_id}'")
