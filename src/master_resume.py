"""The one door onto ``master_data/resume.yaml``.

The master resume is read in three places (the pipeline, the Coach context
builder, the single-job worker) and written in two (the AI import during
onboarding, and the raw text editor). That is enough doors for a shape to drift
between them, and one did: ``skills``.

``MASTER_RESUME_SCHEMA`` asks the model for a list of ``{group, items}`` objects
because structured output is far more reliable with fixed keys than with
arbitrary ones. The committed template, and every consumer written before that
schema existed, uses a mapping of group name to list. Consumers that reached
straight for ``.items()`` or ``.values()`` therefore crashed on any resume.yaml
produced by the onboarding import — which is the default path for anyone who
signs up and uploads a resume.

The mapping wins. It is what the template ships, what most consumers already
read, and the only one of the two a person can comfortably hand-edit, which
matters because that file is meant to be edited. So the list is folded into a
mapping on the way out of the importer, and anything already sitting on disk in
the old shape is folded on the way in. Neither side of that has to know about
the other, and no consumer has to type ``isinstance`` again.
"""
from __future__ import annotations

from pathlib import Path

import yaml

SkillGroups = dict[str, list[str]]


def normalize_skills(value: object) -> SkillGroups:
    """Return master ``skills`` as a mapping of group name to items.

    Accepts the mapping it will return, the ``{group, items}`` list the schema
    produces, and anything else at all — a hand-edited file can contain a bare
    string or a number, and the callers index the result, so the one outcome
    this must never produce is a surprise type.
    """
    groups: SkillGroups = {}

    if isinstance(value, dict):
        for group, items in value.items():
            name = str(group).strip()
            if name:
                groups.setdefault(name, []).extend(_as_items(items))
        return groups

    if isinstance(value, list):
        for entry in value:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("group") or "").strip()
            # No group name means no home for these items. Inventing one would
            # put a made-up heading on the user's rendered resume.
            if not name:
                continue
            # Duplicate groups merge rather than overwrite: the model can split
            # one heading across two entries, and dropping half a user's skills
            # silently is worse than an oddly ordered merge.
            groups.setdefault(name, []).extend(_as_items(entry.get("items")))
        return groups

    return groups


def _as_items(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def normalize_master(master: dict | None) -> dict:
    """Return the master resume in its canonical shape, without mutating input.

    Only ``skills`` is touched today. The function exists rather than a bare
    ``normalize_skills`` call at each site so the next shape correction has an
    obvious home and does not add a fourth thing for callers to remember.
    """
    if not isinstance(master, dict):
        return {}
    out = dict(master)
    if "skills" in out:
        out["skills"] = normalize_skills(out["skills"])
    return out


def load_master(path: str | Path) -> dict:
    """Read resume.yaml and hand back a normalized dict.

    A missing or empty file is an empty dict, not an error: an account can run
    the web app long before it has a master resume, and every caller here
    already treated absence as "nothing yet".
    """
    path = Path(path)
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return normalize_master(raw)
