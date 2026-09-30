"""Interpret saved search targets consistently across job sources and runs."""
from __future__ import annotations

import re

from .scrapers.schema import Job

_INTERN = re.compile(r"\b(?:intern(?:ship)?|co[ -]?op)\b", re.I)
_FULL_TIME = re.compile(
    r"\b(?:new[ -]?grad(?:uate)?|entry[ -]?level|junior|full[ -]?time|permanent)\b", re.I
)
_TYPE_WORDS = {"intern", "internship", "co", "op", "new", "grad", "graduate",
               "entry", "level", "junior", "full", "time", "permanent"}


def target_kind(keywords: list[str]) -> str:
    """Return the explicitly requested job type; mixed or unspecified means any."""
    joined = " ".join(keywords)
    intern = bool(_INTERN.search(joined))
    full_time = bool(_FULL_TIME.search(joined))
    if intern and not full_time:
        return "internship"
    if full_time and not intern:
        return "full_time"
    return "any"


def wants_internship_source(keywords: list[str]) -> bool:
    """The Simplify source contains only internships, so require explicit intent."""
    return any(_INTERN.search(keyword) for keyword in keywords)


def matches_keywords(text: str, keywords: list[str]) -> bool:
    """Match role words in any order; job-type words are checked separately."""
    if not keywords:
        return True
    haystack = set(re.findall(r"[a-z0-9]+", text.lower()))
    role_terms = []
    for keyword in keywords:
        words = set(re.findall(r"[a-z0-9]+", keyword.lower()))
        terms = words - _TYPE_WORDS
        if terms:
            role_terms.append(terms)
        elif not ({"full", "time", "permanent"} & words):
            role_terms.append(words)
    return not role_terms or any(terms <= haystack for terms in role_terms)


def allows_job(job: Job, search: dict) -> bool:
    kind = target_kind(search.get("keywords") or [])
    is_intern = bool(_INTERN.search(job.title or ""))
    if kind == "full_time" and is_intern:
        return False
    if kind == "internship" and not is_intern:
        return False

    location = (job.location or "").casefold()
    is_remote = job.remote or "remote" in location
    if is_remote:
        return bool(search.get("remote_ok", True))
    cities = [city.strip().casefold() for city in search.get("onsite_cities") or []
              if city.strip()]
    return not cities or any(city in location for city in cities)
