"""Compatibility entry point for the evidence-led resume pipeline.

Historically this module contained a large self-correcting graph dominated by
keyword fixing and exact bullet line bands. Callers retain the same public
function while the implementation now lives in the deeper ``resume_pipeline``
module. The project-ranking helper remains for callers that relied on its
stable, non-mutating ordering behavior.
"""
from __future__ import annotations

import re

from .providers import LLMProvider
from .resume_pipeline import run_resume_editorial_pipeline


_TOKEN_RE = re.compile(r"[a-z0-9+#.]+")


def _rank_projects_by_jd(projects: list[dict], jd_text: str) -> list[dict]:
    """Return a relevance-ordered copy without mutating the master resume."""
    if not projects:
        return projects
    jd_tokens = set(_TOKEN_RE.findall((jd_text or "").lower()))
    if not jd_tokens:
        return list(projects)

    def score(project: dict) -> int:
        text = " ".join([
            str(project.get("name", "")),
            str(project.get("tech", "")),
            " ".join(project.get("bullets_all") or []),
        ]).lower()
        return len(set(_TOKEN_RE.findall(text)) & jd_tokens)

    indexed = list(enumerate(projects))
    indexed.sort(key=lambda value: (-score(value[1]), value[0]))
    return [project for _, project in indexed]


def run_tailor_graph(
    master_resume: dict,
    job: dict,
    tailor_chain: list[LLMProvider],
    critique_chain: list[LLMProvider],
    stories: list | None = None,
    guidelines: list | None = None,
    metrics_sink: dict | None = None,
    relinefit_chain: list[LLMProvider] | None = None,
) -> dict:
    """Run the v2 evidence-selection, editorial, and grounding stages.

    ``relinefit_chain`` is accepted for configuration compatibility but is no
    longer used. Layout repair belongs after content generation and factual
    validation, and it never rewrites prose to satisfy character bands.
    """
    return run_resume_editorial_pipeline(
        master_resume,
        job,
        writer_chain=tailor_chain,
        verifier_chain=critique_chain or tailor_chain,
        stories=stories,
        guidelines=guidelines,
        metrics_sink=metrics_sink,
    )
