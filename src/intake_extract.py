"""Deterministic derivation of conversation chips from a user's own words.

Pure functions only: no I/O, no LLM, no imports from ``server``. The onboarding
journey runs before the user has an API key, so everything here must work with
nothing but text.

The vocabulary and company list are passed in rather than imported so these
functions stay trivially testable and the caller owns the I/O.
"""
from __future__ import annotations

import re

# A tag is lowercase, starts with a letter, and may contain digits, hyphens,
# dots or plus signs (c++, node.js, ml-engineer). Two characters minimum, since
# real tags like "ai" and "ml" are that short.
_TAG = re.compile(r"^[a-z][a-z0-9.+-]{1,29}$")


def load_vocabulary(index_md: str) -> set[str]:
    """Parse the ``## Tag taxonomy`` section of a stories ``_INDEX.md``.

    The section is a series of ``**Label:** a, b, c`` lines whose lists may wrap
    onto following lines. Only those payloads are read: prose elsewhere in the
    file, the bold labels themselves, and the heading's own parenthetical are
    all excluded, because any of them becoming a "tag" would surface as a
    nonsense chip in front of the user.
    """
    _, _, tail = index_md.partition("## Tag taxonomy")
    if not tail:
        return set()

    payloads: list[str] = []
    capturing = False
    for line in tail.splitlines():
        stripped = line.strip()
        if ":**" in stripped:
            capturing = True
            payloads.append(stripped.split(":**", 1)[1])
            continue
        if not stripped:
            capturing = False
            continue
        if capturing:
            payloads.append(stripped)

    vocab: set[str] = set()
    for chunk in payloads:
        chunk = re.sub(r"\([^)]*\)", " ", chunk)
        for raw in chunk.split(","):
            token = raw.strip().strip(".").lower()
            if _TAG.match(token):
                vocab.add(token)
    return vocab
