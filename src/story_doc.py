"""The one door onto a ``master_data/stories/*.md`` file.

A story is YAML frontmatter followed by prose. The frontmatter is structured
data — ``tags``, ``role_fit`` and ``company_fit`` decide which story a cover
letter gets built from, and ``reference_loader._score`` pays +5 for a tag that
matches the detected role category against +0.25 for a body keyword. Asking a
user to hand-type that in a textarea is asking them to hand-type the part that
actually matters.

Reading is deliberately tolerant: a file mid-edit, or one where somebody wrote
``tags: platform`` instead of a list, still has to open in the form rather than
refuse. Writing is lossless: the body is copied through verbatim and any
frontmatter key or comment the form does not model stays where it was.

``reference_loader`` still owns reading stories *for matching*; this module owns
the round trip for *editing* one.
"""
from __future__ import annotations

from io import StringIO

import yaml

# The frontmatter keys the structured editor owns, in the order a new file gets
# them. Matches ``content_studio._STORY_KEYS`` — the AI drafter and the form
# write the same shape.
FRONTMATTER_KEYS: tuple[str, ...] = (
    "title",
    "tags",
    "role_fit",
    "company_fit",
    "one_liner",
)

# The three that are lists of tags. Kept apart from the two scalars because
# every tolerance rule below applies to one group or the other, never both.
LIST_KEYS: tuple[str, ...] = ("tags", "role_fit", "company_fit")


def _split(text: str) -> tuple[str, str]:
    """Return ``(frontmatter_text, body_text)``.

    Same fence handling as ``reference_loader._parse_frontmatter``: split at
    most twice, so a ``---`` inside the prose stays in the prose.
    """
    if not text.startswith("---"):
        return "", text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return "", text
    return parts[1], parts[2]


def _as_tags(value: object) -> list[str]:
    if isinstance(value, str):
        # A hand-edited file can say `tags: platform`. The form indexes these
        # lists, so read the obvious intent rather than hand back a string.
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def parse_story(text: str) -> dict:
    """Read one story file into the shape the form renders."""
    fm_text, body = _split(text)
    try:
        front = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        # Broken frontmatter is still an openable file: the body is the part
        # the user cannot regenerate, and the Advanced tab is how they fix the
        # header.
        front = {}
    if not isinstance(front, dict):
        front = {}

    doc: dict = {"body": body.strip()}
    for key in FRONTMATTER_KEYS:
        if key in LIST_KEYS:
            doc[key] = _as_tags(front.get(key))
        else:
            doc[key] = str(front.get(key) or "").strip()
    return doc


def render_story(existing_text: str, data: dict) -> str:
    """Merge ``data`` into ``existing_text`` and return the markdown to write.

    Only keys present in ``data`` are replaced, so a caller that sends just
    ``tags`` keeps the title, the body and everything else. The frontmatter is
    round-tripped through ruamel rather than dumped fresh, which keeps key
    order, quoting style and any comment sitting in the header.
    """
    from ruamel.yaml import YAML
    from ruamel.yaml.comments import CommentedMap

    fm_text, body = _split(existing_text)

    rt = YAML()
    rt.preserve_quotes = True
    # A one-liner is easily past 80 characters, and ruamel's default wrap would
    # fold it into a multi-line scalar that reads as a change in the next diff.
    rt.width = 4096

    try:
        front = rt.load(fm_text) if fm_text.strip() else None
    except Exception:
        front = None
    if not isinstance(front, CommentedMap):
        front = CommentedMap()

    for key in FRONTMATTER_KEYS:
        if key not in data:
            continue
        # Plain assignment, unlike the resume's in-place merge: a story header
        # is five short keys of bare tags, so there are no per-item comments to
        # preserve and ruamel keeps a comment attached to the key itself.
        front[key] = list(_as_tags(data[key])) if key in LIST_KEYS else str(data[key])

    if "body" in data:
        body = str(data["body"])

    buf = StringIO()
    rt.dump(front, buf)
    return f"---\n{buf.getvalue().strip()}\n---\n\n{body.strip()}\n"
