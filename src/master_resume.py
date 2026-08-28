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


# The top-level keys the structured editor owns. Anything else in the file —
# a comment, a key the schema does not model — belongs to the user and is
# copied through untouched.
FORM_KEYS: tuple[str, ...] = (
    "profile",
    "summary_options",
    "core_skills",
    "ats_adjacent_skills",
    "skills",
    "experience",
    "projects",
    "education",
)


def render_master(existing_text: str, data: dict) -> str:
    """Merge ``data`` into ``existing_text`` and return the YAML to write.

    Round-trips through ruamel rather than dumping a fresh document, so
    comments, key order and unmodelled keys survive. Only keys present in
    ``data`` are replaced: a section the caller omitted is left exactly as it
    was, because the form saves what it renders and must not erase what it
    does not.
    """
    from io import StringIO

    from ruamel.yaml import YAML
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    rt = YAML()
    rt.preserve_quotes = True
    # ruamel wraps at 80 by default, which would fold a long bullet into a
    # multi-line scalar and surface as a phantom change in the next diff.
    rt.width = 4096

    doc = rt.load(existing_text) if existing_text.strip() else None
    if not isinstance(doc, (dict, CommentedMap)):
        doc = CommentedMap()

    incoming = normalize_master(data)
    for key in FORM_KEYS:
        if key not in incoming:
            continue
        existing = doc.get(key) if isinstance(doc, CommentedMap) else None
        if isinstance(existing, (CommentedMap, CommentedSeq)):
            _merge_into(existing, incoming[key])
        else:
            doc[key] = incoming[key]

    buf = StringIO()
    rt.dump(doc, buf)
    return buf.getvalue()


def _merge_into(old, new):
    """Update a ruamel container in place so its value equals ``new``.

    A plain ``doc[key] = new_value`` replaces the whole ruamel node, which
    discards any comment ruamel attached to that node (e.g. a comment sitting
    between a list's last item and the next map key is stored as a trailing
    comment on that item, not on the following key — replacing the list wholesale
    loses it). Assigning by index/key instead mutates the existing node, so
    ruamel's comment map — keyed by index/key — keeps pointing at the right
    place. Falls back to plain replacement when the container types don't match
    (nothing to preserve) or when a nested value isn't a container.
    """
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    if isinstance(old, CommentedSeq) and isinstance(new, list):
        while len(old) > len(new):
            del old[-1]
        for i, item in enumerate(new):
            if i < len(old):
                if isinstance(old[i], (CommentedMap, CommentedSeq)) and isinstance(
                    item, (dict, list)
                ):
                    _merge_into(old[i], item)
                else:
                    old[i] = item
            else:
                old.append(item)
        return
    if isinstance(old, CommentedMap) and isinstance(new, dict):
        for k in list(old.keys()):
            if k not in new:
                del old[k]
        for k, v in new.items():
            existing = old.get(k)
            if isinstance(existing, (CommentedMap, CommentedSeq)) and isinstance(
                v, (dict, list)
            ):
                _merge_into(existing, v)
            else:
                old[k] = v
        return
