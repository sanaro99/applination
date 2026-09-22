"""Optional Braintrust publisher for completed local editorial evaluations.

This module does not execute model calls and is never imported by production
pipeline code.  The local evaluator remains authoritative; publishing is an
explicit, post-run action restricted to cases marked safe for cloud upload.
"""
from __future__ import annotations

import os
from typing import Any, Callable, Iterable

from .editorial_evaluation import EditorialEvaluationCase


def braintrust_scores(record: dict[str, Any]) -> dict[str, float]:
    """Flatten domain scores into Braintrust's numeric 0..1 score shape."""
    scores: dict[str, float] = {"run_ok": 1.0 if record.get("ok") else 0.0}
    if not record.get("ok"):
        return scores

    groups = record.get("scores") or {}
    resume = groups.get("resume") or {}
    letter = groups.get("cover_letter") or {}
    expectations = groups.get("expectations") or {}

    scores.update({
        "grounding_passed": 1.0 if resume.get("grounding_passed") else 0.0,
        "no_unsupported_numbers": 1.0 if not (
            resume.get("unsupported_numbers") or letter.get("unsupported_numbers")
        ) else 0.0,
        "cover_letter_valid": 1.0 if not letter.get("validation_issues") else 0.0,
        "expectations_passed": 1.0 if expectations.get("passed", True) else 0.0,
        "sections_complete": 1.0 if not resume.get("missing_sections") else 0.0,
        "core_skills_preserved": 1.0 if not resume.get("missing_core_skills") else 0.0,
    })
    pages = resume.get("rendered_pdf_pages")
    if pages is not None:
        scores["one_page"] = 1.0 if pages == 1 else 0.0
    return scores


def braintrust_metrics(record: dict[str, Any]) -> dict[str, float]:
    groups = record.get("scores") or {}
    resume = groups.get("resume") or {}
    letter = groups.get("cover_letter") or {}
    metrics: dict[str, float] = {
        "latency_ms": float(record.get("latency_ms") or 0),
        "resume_bullets": float(resume.get("bullet_count") or 0),
        "cover_letter_words": float(letter.get("word_count") or 0),
    }
    pages = resume.get("rendered_pdf_pages")
    if isinstance(pages, (int, float)):
        metrics["rendered_pdf_pages"] = float(pages)
    return metrics


def _case_input(case: EditorialEvaluationCase) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "master_resume": case.master_resume,
        "job": case.job,
        "user": case.user,
        "bio": case.bio,
        "stories": case.stories,
    }


def _load_braintrust_init() -> Callable[..., Any]:
    if not os.environ.get("BRAINTRUST_API_KEY"):
        raise RuntimeError(
            "BRAINTRUST_API_KEY is required when --braintrust is enabled"
        )
    try:
        from braintrust import init
    except ImportError as exc:  # pragma: no cover - depends on optional package
        raise RuntimeError(
            "Braintrust publishing needs the optional eval dependency: "
            "pip install -r requirements-eval.txt"
        ) from exc
    return init


def publish_editorial_experiment(
    cases: Iterable[EditorialEvaluationCase],
    records: Iterable[dict[str, Any]],
    *,
    project: str,
    experiment_name: str,
    candidate: dict[str, Any],
    base_experiment: str | None = None,
    allow_sensitive_upload: bool = False,
    init_experiment: Callable[..., Any] | None = None,
) -> dict[str, str]:
    """Publish completed records and return the remote experiment identity.

    Cases are joined by stable case ID rather than list position.  Upload is
    refused unless every case explicitly opts in with ``cloud_safe: true``;
    the CLI escape hatch is intentionally verbose for private local datasets.
    """
    case_list = list(cases)
    record_list = list(records)
    unsafe = [case.case_id for case in case_list if not case.cloud_safe]
    if unsafe and not allow_sensitive_upload:
        raise ValueError(
            "Refusing to upload evaluation cases not marked cloud_safe: "
            + ", ".join(unsafe)
        )

    cases_by_id = {case.case_id: case for case in case_list}
    record_ids = {str(record.get("case_id") or "") for record in record_list}
    missing = sorted(record_ids - set(cases_by_id))
    if missing:
        raise ValueError("Evaluation records have no matching cases: " + ", ".join(missing))

    init_fn = init_experiment or _load_braintrust_init()
    init_args: dict[str, Any] = {
        "project": project,
        "experiment": experiment_name,
        "description": "Applination evidence-led resume and cover-letter evaluation",
        "metadata": {
            "candidate": candidate,
            "publisher": "applination-local-eval",
        },
        "tags": ["editorial-eval"],
        "set_current": False,
    }
    if base_experiment:
        init_args["base_experiment"] = base_experiment
    experiment = init_fn(**init_args)

    for record in record_list:
        case = cases_by_id[str(record.get("case_id") or "")]
        output = None
        if record.get("ok"):
            output = {
                "resume": record.get("resume"),
                "cover_letter": record.get("cover_letter"),
                "scores": record.get("scores"),
            }
        experiment.log(
            input=_case_input(case),
            output=output,
            expected=case.expectations or None,
            error=str(record.get("error") or "") or None,
            scores=braintrust_scores(record),
            metrics=braintrust_metrics(record),
            metadata={
                "case_id": case.case_id,
                "model_candidate": record.get("candidate") or candidate,
                "prompt_versions": record.get("prompt_versions") or {},
            },
        )

    summary = experiment.summarize()
    return {
        "project": project,
        "experiment": str(getattr(experiment, "name", experiment_name)),
        "url": str(getattr(summary, "experiment_url", "") or ""),
    }
