"""Deterministic derivation of conversation chips from a user's own words.

Pure functions only: no I/O, no LLM, no imports from ``server``. The onboarding
journey runs before the user has an API key, so everything here must work with
nothing but text.

The vocabulary and company list are passed in rather than imported so these
functions stay trivially testable and the caller owns the I/O.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

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


# Words that are technically nouns in the right place but always read as noise
# in a chip: the user sees "things you mentioned", and "Inc" is not one.
_STOPLIST = frozenset(
    {
        "inc", "ltd", "llc", "corp", "corporation", "technologies", "technology",
        "solutions", "systems", "services", "group", "company", "team", "the",
        "and", "stuff", "things", "work",
    }
)

# Deliberately conservative: at most two words after the verb. Three would let
# "built the payments migration last year" capture "last year" too, and a chip
# the user did not say is worse than a chip we failed to offer.
_VERB_ANCHOR = re.compile(
    r"\b(?:worked\s+on|built|led|shipped|migrated|designed|launched|ran)\s+"
    r"(?:the\s+|a\s+|an\s+)?"
    r"(?P<obj>[A-Za-z][\w-]*(?:\s+[A-Za-z][\w-]*)?)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Thread:
    """One concrete thing the user mentioned, offered back for them to expand."""

    label: str
    kind: str  # "company" | "topic" | "phrase"


def _dedupe(threads: list[Thread]) -> list[Thread]:
    seen: set[str] = set()
    out: list[Thread] = []
    for thread in threads:
        key = thread.label.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(thread)
    return out


def extract_threads(
    text: str,
    resume_text: str = "",
    *,
    vocabulary: set[str] | None = None,
    companies: Sequence[str] = (),
    limit: int = 8,
) -> list[Thread]:
    """Concrete things the user mentioned, most confident first.

    Order is confidence order — a named company is a surer thing to ask about
    than a verb-anchored phrase — and the cap then keeps the best ones.
    """
    haystack = f"{text}\n{resume_text}"
    low = haystack.lower()
    found: list[Thread] = []

    for slug in companies:
        if slug.lower() in _STOPLIST:
            continue
        if re.search(rf"\b{re.escape(slug.lower())}\b", low):
            found.append(Thread(label=slug.title(), kind="company"))

    for term in sorted(vocabulary or set()):
        if term in _STOPLIST:
            continue
        if re.search(rf"\b{re.escape(term)}\b", low):
            found.append(Thread(label=term, kind="topic"))

    for match in _VERB_ANCHOR.finditer(haystack):
        obj = " ".join(match.group("obj").split()).strip(" .,;:")
        if len(obj) < 3 or obj.lower() in _STOPLIST:
            continue
        if all(word.lower() in _STOPLIST for word in obj.split()):
            continue
        found.append(Thread(label=obj, kind="phrase"))

    return _dedupe(found)[:limit]


_ROLE_WORDS = (
    "engineer", "developer", "scientist", "analyst", "designer", "manager",
    "researcher", "architect", "administrator", "consultant",
)

# Up to two qualifying words before the role noun: "senior data scientist",
# "backend engineer", "engineer".
#
# Qualifiers need two or more characters (``+`` not ``*``). With ``*``, the "m"
# left over from "I'm" is a valid qualifier and "I'm a backend engineer" yields
# "m backend engineer".
_ROLE_TITLE = re.compile(
    r"\b((?:[A-Za-z][\w+#.-]+\s+){0,2}(?:" + "|".join(_ROLE_WORDS) + r"))\b",
    re.IGNORECASE,
)

# Qualifiers that are grammatical filler rather than part of a job title.
_TITLE_NOISE = frozenset({"a", "an", "the", "am", "im", "i'm", "as", "was", "is", "and", "or"})

_DEFAULT_KEYWORDS = ("software engineer", "backend engineer")


@dataclass(frozen=True)
class SearchTerms:
    """What we would go looking for, offered to the user for correction.

    ``guessed`` is True when nothing could be derived and defaults were used, so
    the UI can hedge rather than present a guess as a finding.
    """

    keywords: tuple[str, ...]
    guessed: bool


def _clean_title(raw: str) -> str:
    words = [w for w in raw.split() if w.lower() not in _TITLE_NOISE]
    return " ".join(words).lower().strip()


def extract_search_terms(
    text: str,
    resume_text: str = "",
    *,
    vocabulary: set[str] | None = None,
    limit: int = 6,
) -> SearchTerms:
    """Derive job-search keywords from what the user already told us.

    The user never fills in a search form: we propose from their own words and
    they correct us.
    """
    haystack = f"{text}\n{resume_text}"
    low = haystack.lower()
    keywords: list[str] = []

    for match in _ROLE_TITLE.finditer(haystack):
        title = _clean_title(match.group(1))
        if title and title not in keywords:
            keywords.append(title)

    for term in sorted(vocabulary or set()):
        if term in _STOPLIST:
            continue
        if re.search(rf"\b{re.escape(term)}\b", low) and term not in keywords:
            keywords.append(term)

    if not keywords:
        return SearchTerms(keywords=_DEFAULT_KEYWORDS, guessed=True)
    return SearchTerms(keywords=tuple(keywords[:limit]), guessed=False)
