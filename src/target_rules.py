"""Interpret saved search targets consistently across job sources and runs."""
from __future__ import annotations

import re
from typing import Literal

from .scrapers.schema import Job

JobType = Literal["auto", "any", "full_time", "part_time", "internship", "co_op", "contract", "temporary"]
JOB_TYPES = ("auto", "any", "full_time", "part_time", "internship", "co_op", "contract", "temporary")
_INTERN = re.compile(r"\bintern(?:ship)?\b", re.I)
_CO_OP = re.compile(r"\bco[ -]?op\b", re.I)
_FULL_TIME = re.compile(
    r"\b(?:new[ -]?grad(?:uate)?|entry[ -]?level|junior|full[ -]?time|permanent)\b", re.I
)
_PART_TIME = re.compile(r"\bpart[ -]?time\b", re.I)
_CONTRACT = re.compile(r"\b(?:contract(?:or)?|freelance)\b", re.I)
_TEMPORARY = re.compile(r"\b(?:temp(?:orary)?|fixed[ -]?term|seasonal)\b", re.I)
_HOURS_FULL = re.compile(r"\b(?:full[ -]?time|permanent)\b", re.I)
_VOLUNTEER = re.compile(r"\bvolunteer(?:ing)?\b", re.I)
_ROLE_PHRASES = (
    r"\b(?:contract (?:manager|management|administrator|administration|analyst|"
    r"specialist|officer|coordinator|negotiator)|internship program|temporary works)\b"
)
_TYPE_WORDS = {"intern", "internship", "co", "op", "coop", "new", "grad", "graduate",
               "entry", "level", "junior", "full", "time", "fulltime", "permanent",
               "part", "parttime", "contract", "contractor", "freelance", "temp",
               "temporary", "fixed", "term", "fixedterm", "seasonal"}
_EMPLOYMENT_WORDS = re.compile(
    rf"(?P<role>{_ROLE_PHRASES})|\b(?:intern(?:ship)?|co[ -]?op|full[ -]?time|part[ -]?time|permanent|"
    r"contract(?:or)?|freelance|temp(?:orary)?|fixed[ -]?term|seasonal)\b", re.I
)
_DECLARED_TYPE = (
    r"(?:intern(?:ship)?|co[ -]?op|full[ -]?time|part[ -]?time|permanent|"
    r"contract(?:or)?|freelance|temp(?:orary)?|fixed[ -]?term|seasonal|volunteer)\b"
)
_DECLARATION_PREFIX = r"(?:(?:a|an|paid|unpaid|remote|hybrid|onsite|on-site)\s+)*"
_TYPE_SEQUENCE = (
    rf"{_DECLARED_TYPE}(?:(?:\s+(?:and\s+)?|\s*[,/&]\s*)"
    rf"{_DECLARATION_PREFIX}{_DECLARED_TYPE})*"
)


def _without_role_phrases(text: str) -> str:
    """Role nouns such as Contract Manager are not employment qualifiers."""
    return re.sub(_ROLE_PHRASES, "", text, flags=re.I)


def target_kind(keywords: list[str]) -> str:
    """Return the explicitly requested job type; mixed or unspecified means any."""
    joined = _without_role_phrases(" ".join(keywords))
    kinds = [kind for kind, pattern in (
        ("internship", _INTERN), ("co_op", _CO_OP), ("full_time", _FULL_TIME),
        ("part_time", _PART_TIME), ("contract", _CONTRACT), ("temporary", _TEMPORARY),
    ) if pattern.search(joined)]
    return kinds[0] if len(kinds) == 1 else "any"


def resolve_job_type(search: dict) -> str:
    selected = search.get("job_type", "auto")
    if selected not in JOB_TYPES:
        raise ValueError(f"Unknown search.job_type: {selected}")
    return target_kind(search.get("keywords") or []) if selected == "auto" else selected


def role_keywords(search: dict) -> list[str]:
    """An explicit selection overrides stale employment hints in role keywords."""
    keywords = search.get("keywords") or []
    if search.get("job_type", "auto") == "auto":
        return keywords
    cleaned = [_EMPLOYMENT_WORDS.sub(
        lambda match: match.group("role") or "", keyword,
    ) for keyword in keywords]
    return [value for keyword in cleaned
            if (value := re.sub(r"\s+", " ", keyword).strip(" ,:()/–—-"))]


def typed_query(keyword: str, job_type: str) -> str:
    qualifier = {"internship": "internship", "co_op": "co-op",
                 "contract": "contract", "temporary": "temporary",
                 "full_time": "full-time", "part_time": "part-time"}.get(job_type, "")
    return f"{keyword} {qualifier}".strip()


def wants_internship_source(keywords: list[str], job_type: str | None = None) -> bool:
    """The Simplify source contains only internships, so require explicit intent."""
    if job_type is not None:
        return job_type in {"any", "internship", "co_op"}
    return any(_INTERN.search(keyword) or _CO_OP.search(keyword) for keyword in keywords)


def matches_keywords(text: str, keywords: list[str]) -> bool:
    """Match role words in any order; job-type words are checked separately."""
    if not keywords:
        return True
    haystack = set(re.findall(r"[a-z0-9]+", text.lower()))
    role_terms = []
    for keyword in keywords:
        words = set(re.findall(r"[a-z0-9]+", keyword.lower()))
        terms = words - _TYPE_WORDS
        for role in re.finditer(_ROLE_PHRASES, keyword, re.I):
            terms.update(re.findall(r"[a-z0-9]+", role.group().lower()))
        if terms:
            role_terms.append(terms)
        elif not ({"full", "time", "permanent"} & words):
            role_terms.append(words)
    return not role_terms or any(terms <= haystack for terms in role_terms)


def _type_from_text(text: str) -> str:
    text = text.replace("_", " ")
    for kind, pattern in (
        ("co_op", _CO_OP), ("internship", _INTERN), ("temporary", _TEMPORARY),
        ("contract", _CONTRACT), ("part_time", _PART_TIME),
        ("volunteer", _VOLUNTEER), ("full_time", _HOURS_FULL),
    ):
        if pattern.search(text):
            return kind
    return "unknown"


def posting_job_type(job: Job) -> str:
    """Prefer title/type metadata; inspect only explicit declarations in the JD."""
    hints = [_without_role_phrases(job.title), getattr(job, "employment_type", "")]
    description = _without_role_phrases(job.description or "")
    for pattern in (
        rf"\b(?:employment|job|position|contract)(?:\s+(?:type|time))?\s*:\s*{_DECLARATION_PREFIX}({_TYPE_SEQUENCE})",
        rf"\b(?:this|the)\s+(?:role|position|job)\s+(?:is|will be)\s+{_DECLARATION_PREFIX}({_TYPE_SEQUENCE})",
        rf"\bthis is {_DECLARATION_PREFIX}({_TYPE_SEQUENCE})",
    ):
        for declaration in re.finditer(pattern, description, re.I):
            hints.append(declaration.group(1))
    # A contract/temporary/intern role may also have full-time working hours.
    return _type_from_text(" ".join(hints))


def allows_job(job: Job, search: dict) -> bool:
    kind = resolve_job_type(search)
    actual = posting_job_type(job)
    if kind == "full_time" and actual not in {"full_time", "unknown"}:
        return False
    if kind not in {"full_time", "any"} and actual != kind:
        return False

    location = (job.location or "").casefold()
    is_remote = job.remote or "remote" in location
    if is_remote:
        return bool(search.get("remote_ok", True))
    cities = [city.strip().casefold() for city in search.get("onsite_cities") or []
              if city.strip()]
    return not cities or any(city in location for city in cities)
