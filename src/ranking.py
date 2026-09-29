"""Dependency-free, lexical BM25 ranking. No models, training, or network calls."""
from __future__ import annotations

import math
import re
from collections import Counter
from html import unescape

from .scrapers.schema import strip_html

_STOP_WORDS = set("""
a an and are as at be been being by can could for from has have how in into is it
its of on or our that the their them these they this those to was we were what
when where which who will with you your also about all any both each other over
such than then through under up us using use used work working team teams
company candidate experience experienced skills skill projects project summary
key job jobs role roles position opportunity opportunities required requirements
preferred including include must should may years year intern internship
full time new grad graduate applications application responsibilities
""".split())
_TOKEN = re.compile(r"\.net\b|[a-z0-9]+(?:\+\+|#)?")
_ALIASES = (
    (r"\b(?:postgres|postgresql)\b", "postgresql"),
    (r"\b(?:k8s|kubernetes)\b", "kubernetes"),
    (r"\b(?:golang|go)\b", "golang"),
    (r"\b(?:node\.?js|node\.js)\b", "nodejs"),
    (r"\b(?:react\.?js|react\.js)\b", "react"),
    (r"\b(?:javascript|js)\b", "javascript"),
    (r"\b(?:typescript|ts)\b", "typescript"),
    (r"\b(?:amazon web services|aws)\b", "aws"),
    (r"\b(?:google cloud(?: platform)?|gcp)\b", "gcp"),
    (r"\b(?:machine learning|ml)\b", "ml"),
    (r"\b(?:artificial intelligence|ai)\b", "ai"),
)


def ranking_method(llm_cfg: dict) -> str:
    """Read the opt-in method; old configs keep their existing LLM behavior."""
    task = ((llm_cfg.get("tasks") or {}).get("ranking") or {})
    method = task.get("method")
    if method is None:
        return "llm"
    if method not in ("llm", "bm25"):
        raise ValueError(f"Unknown ranking method {method!r}; choose 'llm' or 'bm25'.")
    return method


def _tokens(text: str) -> list[str]:
    text = unescape(strip_html(text or "")).lower()
    for pattern, replacement in _ALIASES:
        text = re.sub(pattern, replacement, text)
    return [t for t in _TOKEN.findall(text) if t not in _STOP_WORDS and not t.isdigit()]


def _query(profile: str, master: dict | None, keywords: list[str]) -> dict[str, float]:
    weights: dict[str, float] = {}

    def add(text: str, weight: float) -> None:
        for term in set(_tokens(text)):
            weights[term] = max(weights.get(term, 0), weight)

    if master is None:
        add(profile, 1)
    else:
        for summary in master.get("summary_options") or []:
            add(summary, 0.25)
        skills = list(master.get("core_skills") or [])
        for group in (master.get("skills") or {}).values():
            skills.extend(group)
        for skill in skills:
            add(skill, 3)
        for section in ("experience", "projects", "education"):
            for entry in master.get(section) or []:
                for key in ("role", "name", "tech", "degree"):
                    add(entry.get(key, ""), 0.25)
                for line in entry.get("bullets_all") or entry.get("bullets") or entry.get("coursework") or []:
                    add(line, 0.25)
    for keyword in keywords:
        add(keyword, 2)
    # Long narratives should not outweigh explicit skills and search intent.
    narrative_weight = sum(w for w in weights.values() if w <= 0.25)
    if narrative_weight > 3:
        for term, weight in weights.items():
            if weight <= 0.25:
                weights[term] *= 3 / narrative_weight
    return weights


def rank_jobs(
    jobs: list[dict],
    user_profile: str,
    *,
    master_resume: dict | None = None,
    keywords: list[str] | None = None,
) -> list[dict]:
    """Score every job with the same {idx, score, reason} contract as the LLM.

    BM25 uses k1=1.2 and b=0.75, with title terms boosted 3x. Query terms
    prioritize actual resume skills and search preferences over narrative text.
    Absolute scores use 90% weighted term coverage with fixed TF saturation,
    plus 10% normalized BM25/IDF and document-length relevance. Keeping
    corpus-dependent influence small prevents scores collapsing as matching
    or sparse postings accumulate. Both components retain unmatched terms:
    the best job in a weak pool is never automatically promoted to 100.
    This is a relevance score,
    not a probability of being hired or the same scale as an LLM fit score.
    """
    if not jobs:
        return []
    query = _query(user_profile, master_resume, keywords or [])
    documents = []
    for job in jobs:
        terms = Counter(_tokens(job.get("desc") or ""))
        terms.update(_tokens(job.get("title") or "") * 3)
        documents.append(terms)
    avg_length = sum(d.total() for d in documents) / len(documents) or 1
    frequencies = Counter(term for doc in documents for term in doc)
    idf = {
        term: math.log1p((len(jobs) - frequencies[term] + 0.5) / (frequencies[term] + 0.5))
        for term in query
    }
    k1, b = 1.2, 0.75
    maximum = (k1 + 1) * sum(query[t] * idf[t] for t in query)
    coverage_maximum = (k1 + 1) * sum(query.values())
    results = []
    for idx, doc in enumerate(documents):
        norm = k1 * (1 - b + b * doc.total() / avg_length)
        coverage = {
            term: query[term] * doc[term] * (k1 + 1) / (doc[term] + k1)
            for term in query if doc[term]
        }
        contributions = {
            term: query[term] * idf[term] * doc[term] * (k1 + 1) / (doc[term] + norm)
            for term in coverage
        }
        raw = sum(contributions.values())
        absolute = math.sqrt(min(1, sum(coverage.values()) / coverage_maximum)) if coverage_maximum else 0
        relative = math.sqrt(min(1, raw / maximum)) if maximum else 0
        score = round(90 * absolute + 10 * relative)
        matches = sorted(contributions, key=lambda t: (-query[t], -contributions[t], t))[:6]
        reason = (
            "Local BM25; matched terms: " + ", ".join(matches) + "."
            if matches else "Local BM25; no matching profile or search terms."
        )
        results.append({"idx": idx, "score": score, "reason": reason})
    return results
