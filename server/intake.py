"""Read and write the per-user ``_intake`` tree.

The onboarding journey captures raw human material before the user has an API
key, so nothing here calls a provider. Enrichment (plan 2) turns this material
into ``resume.yaml``, tagged stories and ``bio.md`` once a key exists.

This module is the only place that knows the intake layout; everything else
goes through these functions.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from .user_paths import UserPaths, resolve_within

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_FRONTMATTER = re.compile(r"^---\n(?P<meta>.*?)\n---\n(?P<body>.*)$", re.S)


def slugify(text: str) -> str:
    """A filesystem-safe slug. Never empty, never contains a path separator.

    Titles are user-supplied, so this is the first of two defences: the slug
    cannot express traversal, and ``resolve_within`` then proves containment
    anyway. Either alone would be enough; both is cheap.
    """
    slug = _SLUG_STRIP.sub("-", text.lower()).strip("-")[:60].strip("-")
    return slug or "story"


def save_notes(paths: UserPaths, text: str) -> Path:
    paths.ensure()
    paths.intake_notes_path.write_text(text, encoding="utf-8")
    return paths.intake_notes_path


def read_notes(paths: UserPaths) -> str:
    if not paths.intake_notes_path.exists():
        return ""
    return paths.intake_notes_path.read_text(encoding="utf-8")


def park_resume(paths: UserPaths, text: str) -> Path:
    """Store extracted resume *text* as-is.

    Deliberately not parsed into ``resume.yaml``: that needs an LLM, and the
    journey runs before there is a key. Parking means capture cannot fail
    because a model was down, a key was wrong, or a quota was hit.
    """
    paths.ensure()
    paths.intake_resume_path.write_text(text, encoding="utf-8")
    return paths.intake_resume_path


def read_parked_resume(paths: UserPaths) -> str:
    if not paths.intake_resume_path.exists():
        return ""
    return paths.intake_resume_path.read_text(encoding="utf-8")


def _unique_path(directory: Path, slug: str) -> Path:
    candidate = resolve_within(directory, f"{slug}.md")
    counter = 2
    while candidate.exists():
        candidate = resolve_within(directory, f"{slug}-{counter}.md")
        counter += 1
    return candidate


def save_draft_story(paths: UserPaths, title: str, body: str) -> Path:
    """Save one told story verbatim, as a draft.

    The body is written untouched. It is the user's own words, and enrichment
    later works from them — editing here would mean the model shapes what it is
    later asked to shape.
    """
    paths.ensure()
    path = _unique_path(paths.intake_stories_dir, slugify(title))
    captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    safe_title = title.replace('"', "'")
    path.write_text(
        f'---\ndraft: true\ntitle: "{safe_title}"\ncaptured_at: "{captured_at}"\n---\n\n{body}',
        encoding="utf-8",
    )
    return path


def _parse_draft(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(text)
    meta: dict[str, str] = {}
    body = text
    if match:
        body = match.group("body")
        for line in match.group("meta").splitlines():
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip().strip('"')
    return {
        "slug": path.stem,
        "title": meta.get("title", path.stem),
        "captured_at": meta.get("captured_at", ""),
        "body": body,
    }


def list_drafts(paths: UserPaths) -> list[dict]:
    if not paths.intake_stories_dir.exists():
        return []
    return [_parse_draft(p) for p in sorted(paths.intake_stories_dir.glob("*.md"))]
