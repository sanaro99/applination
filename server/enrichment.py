"""Turn captured raw material into real master data, one step at a time.

The journey deliberately runs before the user has an API key, so every AI
transformation lands here instead of inline at capture time. That separation
also means capture never fails because a model was down, a key was wrong or a
quota was hit — and each step below is independently retryable.

The client drives the steps one at a time so that ridge animation reflects real
progress rather than a timed fake, and so a single failure is retryable in place
without restarting the cascade.
"""
from __future__ import annotations

import logging

from . import intake as intake_store
from .db import User
from .deps import paths_for

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
            {"id": "resume", "label": "Reading your resume", "ridge": "resume"}
        )

    drafts = intake_store.list_drafts(paths)
    for index, draft in enumerate(drafts, start=1):
        steps.append(
            {
                "id": f"story:{draft['slug']}",
                "label": f"Shaping “{draft['title']}”",
                "ridge": f"story_{min(index, 3)}",
            }
        )

    notes = intake_store.read_notes(paths).strip()
    if notes and not paths.bio_path.exists():
        steps.append({"id": "bio", "label": "Learning your voice", "ridge": "voice"})

    if parked or notes or drafts:
        steps.append(
            {"id": "search", "label": "Working out what to look for", "ridge": "search"}
        )

    return steps
