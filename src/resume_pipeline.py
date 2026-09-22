"""Evidence-led editorial pipeline for tailored resumes.

This replaces the former character-band graph with five explicit stages:
evidence normalization, content planning, editorial writing, grounding review,
and narrowly scoped repair.  Layout is intentionally downstream in
``resume_builder``.
"""
from __future__ import annotations

from copy import deepcopy
import json
import logging
import time
from typing import Callable

from .evidence import (
    EvidenceItem,
    build_evidence_ledger,
    finalize_resume,
    format_evidence_packet,
    job_focus_text,
    normalize_content_plan,
    selected_evidence_ids,
)
from .grounding import (
    DeterministicGroundingAdapter,
    GroundingEngine,
    LLMProviderChainGroundingAdapter,
    blocking_verdicts,
    prune_unsupported,
)
from .profile import derive_profile
from .providers import LLMProvider
from .schemas import CONTENT_PLAN_SCHEMA, RESUME_SCHEMA


LOG = logging.getLogger(__name__)


def _call_json_chain(
    providers: list[LLMProvider],
    system: str,
    user: str,
    *,
    schema: dict,
    max_tokens: int,
    stage: str,
    validate: Callable[[dict], bool] | None = None,
) -> tuple[dict, str]:
    last_error: Exception | None = None
    for provider in providers:
        try:
            value = provider.json_call(system, user, max_tokens=max_tokens, schema=schema)
            if isinstance(value, dict) and value and (validate is None or validate(value)):
                return value, provider.name
            raise ValueError("provider returned empty or structurally invalid JSON")
        except Exception as exc:
            last_error = exc
            LOG.warning("%s failed on %s: %s", stage, provider.name, str(exc)[:180])
    raise RuntimeError(f"{stage} failed on all providers: {last_error}")


def _record_stage(metrics: dict, name: str, started: float, **details) -> None:
    metrics.setdefault("stages", []).append({
        "name": name,
        "seconds": round(time.time() - started, 3),
        **details,
    })


def _plan_content(
    master: dict,
    job: dict,
    ledger: list[EvidenceItem],
    providers: list[LLMProvider],
    guidelines: list[dict],
) -> tuple[dict, str]:
    system = (
        "You are a resume content strategist. Select the strongest truthful evidence for "
        "this specific job before any prose is written. Prefer relevance and credible "
        "outcomes over recency or a fixed template. You may select multiple evidence IDs "
        "for one future bullet so the writer can merge them, or one evidence ID for multiple "
        "future bullets when it contains distinct facts. Do not write resume prose.\n\n"
        "Classify skill support carefully: direct means the source names the skill; entailed "
        "means it is unavoidable from the work; adjacent means only transferable knowledge. "
        "You may propose at most two adjacent skills only when the job explicitly asks for "
        "them and the cited evidence shows a technically defensible transfer. They must be "
        "presented as familiarity or transferable foundations, never as hands-on experience. "
        "Use variable bullet counts. Plan roughly 8-12 bullets total, with more space for the "
        "most relevant work and less for weakly related history. Keep core_skills in every plan, "
        "normally select two job-relevant projects when at least two exist, and preserve all "
        "available resume sections. Prefer concrete technical impact over award-only bullets "
        "when the Awards section already carries the same recognition. Keep this plan compact: "
        "at most five requirement rows, "
        "6-12 selected skill rows (including core skills), eight ATS keywords, and reasons under "
        "eight words. The downstream finalizer preserves broader direct skills; do not enumerate "
        "the entire source inventory. Return one JSON object with the contract's top-level keys."
    )
    guideline_text = "\n".join(
        (item.get("body") or "")[:500] for item in guidelines[:3] if item.get("body")
    )
    user = (
        f"JOB:\n{job.get('company', '')} | {job.get('title', '')} | {job.get('location', '')}\n"
        f"{job_focus_text(job)[:3000]}\n\n"
        f"SOURCE EVIDENCE:\n{format_evidence_packet([item for item in ledger if item.kind != 'story'], max_chars_per_item=400)}\n\n"
        f"PINNED CORE SKILLS:\n{json.dumps(master.get('core_skills') or [])}\n\n"
        f"CURATED PROJECT PREFERENCES (soft tie-breaker only):\n"
        f"{json.dumps(master.get('preferred_projects') or [])}\n\n"
        f"OPTIONAL EDITORIAL GUIDELINES:\n{guideline_text}\n\n"
        "Produce the content plan. Every selected item must cite IDs exactly as shown."
    )
    required_lists = ("selected_experience", "selected_projects", "selected_skills", "summary_evidence_ids")
    valid_sources = {item.source_id for item in ledger}
    def valid_plan(plan: dict) -> bool:
        return (
            all(isinstance(plan.get(key), list) for key in required_lists)
            and (not master.get("experience") or bool(plan["selected_experience"]))
            and (not master.get("projects") or bool(plan["selected_projects"]))
            and all(
                isinstance(row, dict) and str(row.get("source_id")) in valid_sources
                for key in ("selected_experience", "selected_projects")
                for row in plan[key]
            )
        )

    return _call_json_chain(
        providers, system, user, schema=CONTENT_PLAN_SCHEMA, max_tokens=2200,
        stage="content_plan", validate=valid_plan,
    )


def _writer_prompt(
    master: dict,
    job: dict,
    profile: dict,
    plan: dict,
    packet: str,
    guidelines: list[dict],
) -> tuple[str, str]:
    titles = ", ".join(profile.get("identity_titles") or ["professional"])
    guidelines_text = "\n".join(
        (item.get("body") or "")[:500] for item in guidelines[:3] if item.get("body")
    )
    system = (
        "You are the editorial writer in an evidence-led resume pipeline. Write a highly "
        "job-specific ATS-readable resume from the approved content plan and source evidence.\n\n"
        "HARD CONSTRAINTS:\n"
        "1. Employers, roles, dates, schools, metrics, technologies, responsibilities, and "
        "outcomes must be direct or faithfully entailed by the evidence.\n"
        "2. You MAY rewrite, compress, expand for clarity, merge multiple source bullets, split "
        "one source bullet into distinct concise bullets, and reorder evidence. Preserve meaning.\n"
        "3. Never turn adjacent knowledge into claimed hands-on experience. Adjacent knowledge may "
        "appear in the summary with explicit transfer language. In skills, put it under a 'Related "
        "Knowledge' group and qualify every item in the item text, for example 'MongoDB (transferable "
        "familiarity)'. Never imply production use.\n"
        "4. Never invent a number, tool, employer, title, responsibility, ownership level, or outcome.\n"
        "5. Use only selected source identities and return valid JSON matching the schema.\n"
        "6. Include the source's certifications and awards unchanged; do not invent honors. "
        "Include every pinned core skill.\n\n"
        "EDITORIAL PREFERENCES, NOT VALIDATION BANDS:\n"
        "- Select and order bullets strongest-first for this job. Identities will be displayed "
        "newest-first; do not distort their dates.\n"
        "- Most bullets should be compact enough for roughly one printed line (usually 85-145 "
        "characters). A 1.5-line bullet is fine. Reserve a full two-line bullet (up to roughly "
        "230 characters) for at most 1-3 genuinely important achievements. Do not pad text to a target.\n"
        "- Use variable bullet counts, generally 2-5 per experience and 1-2 per project.\n"
        "- Avoid repeating an award as an experience bullet when the Awards section already "
        "shows it; use that space for distinctive technical work.\n"
        "- A bullet needs a metric only when the evidence contains one. Specific qualitative "
        "outcomes are better than invented scale.\n"
        "- Aim for about 30-40 role-relevant skills across compact categories, including the "
        "pinned core. Most must be direct or entailed; include at most two qualified adjacent "
        "items. Keep each category short enough to fit a single printed line.\n"
        "- Write a concise 2-3 sentence summary that sounds specific to this role without adopting "
        "an unsupported job title. No em dashes."
    )
    user = (
        f"CANDIDATE POSITIONING:\nReal identity titles: {titles}\n"
        f"Seniority: {profile.get('seniority', 'professional')}\n\n"
        f"JOB:\n{job.get('company', '')} | {job.get('title', '')}\n"
        f"{job_focus_text(job)[:2800]}\n\n"
        f"APPROVED CONTENT PLAN:\n{json.dumps(plan, separators=(',', ':'))}\n\n"
        f"PINNED CORE SKILLS:\n{json.dumps(master.get('core_skills') or [])}\n\n"
        f"SELECTED SOURCE EVIDENCE:\n{packet}\n\n"
        f"OPTIONAL WRITING GUIDELINES:\n{guidelines_text}\n\n"
        "Return the tailored resume JSON. The final ats_keywords field is metadata, not permission "
        "to insert unsupported keywords into visible content."
    )
    return system, user


def _fallback_draft(master: dict, plan: dict) -> dict:
    def selected_bullets(source: dict, selection: dict) -> list[str]:
        pool = list(source.get("bullets_all") or source.get("bullets") or [])
        chosen = []
        for evidence_id in selection.get("evidence_ids") or []:
            try:
                index = int(str(evidence_id).rsplit(".bullet.", 1)[1])
            except (IndexError, ValueError):
                continue
            if index < len(pool) and pool[index] not in chosen:
                chosen.append(pool[index])
        return chosen or pool

    exp = []
    for selection in plan.get("selected_experience") or []:
        try:
            source = (master.get("experience") or [])[int(selection["source_id"].split(".")[1])]
        except (IndexError, KeyError, TypeError, ValueError):
            continue
        exp.append({
            "company": source.get("company", ""), "role": source.get("role", ""),
            "location": source.get("location", ""),
            "dates": " - ".join(filter(None, [source.get("start_date"), source.get("end_date")])),
            "bullets": selected_bullets(source, selection)[:selection.get("target_bullets", 3)],
        })
    projects = []
    for selection in plan.get("selected_projects") or []:
        try:
            source = (master.get("projects") or [])[int(selection["source_id"].split(".")[1])]
        except (IndexError, KeyError, TypeError, ValueError):
            continue
        projects.append({
            "name": source.get("name", ""), "tech": source.get("tech", ""),
            "link": source.get("link", ""),
            "dates": " - ".join(filter(None, [source.get("start_date"), source.get("end_date")])),
            "bullets": selected_bullets(source, selection)[:selection.get("target_bullets", 1)],
        })

    grouped: dict[str, list[str]] = {}
    raw_skills = master.get("skills") or {}
    if isinstance(raw_skills, dict):
        for group, values in raw_skills.items():
            if isinstance(values, list) and values:
                grouped[str(group)] = [str(value) for value in values]
    elif isinstance(raw_skills, list):
        for row in raw_skills:
            if isinstance(row, dict) and row.get("items"):
                grouped[str(row.get("group") or "Skills")] = list(row["items"])
    return {
        "summary": str((master.get("summary_options") or [""])[0]),
        "skills": [{"group": key, "items": values} for key, values in grouped.items()],
        "experience": exp,
        "projects": projects,
        "education": deepcopy(master.get("education") or []),
        "certifications": deepcopy(master.get("certifications") or []),
        "awards": deepcopy(master.get("awards") or []),
        "ats_keywords": list(plan.get("ats_keywords") or []),
    }


def _repair_resume(
    draft: dict,
    report: dict,
    plan: dict,
    packet: str,
    providers: list[LLMProvider],
) -> tuple[dict, str]:
    system = (
        "You are performing a narrowly scoped factual repair. Correct only the claims identified "
        "by the grounding report. Preserve all safe content and the selected structure. Replace an "
        "unsupported claim with a supported formulation when possible; otherwise remove it. Never "
        "add evidence, metrics, or tools. Return the complete corrected resume JSON only."
    )
    user = (
        f"CONTENT PLAN:\n{json.dumps(plan, indent=2)}\n\n"
        f"SOURCE EVIDENCE:\n{packet}\n\n"
        f"CURRENT RESUME:\n{json.dumps(draft, indent=2)}\n\n"
        f"GROUNDING REPORT:\n{json.dumps(report, indent=2)}\n\n"
        "Return the complete resume with only the necessary factual repairs."
    )
    return _call_json_chain(
        providers, system, user, schema=RESUME_SCHEMA, max_tokens=2800, stage="grounding_repair",
    )


def _strip_em_dashes(value):
    if isinstance(value, str):
        return value.replace(" — ", ", ").replace("—", ", ")
    if isinstance(value, list):
        return [_strip_em_dashes(item) for item in value]
    if isinstance(value, dict):
        return {key: _strip_em_dashes(item) for key, item in value.items()}
    return value


def run_resume_editorial_pipeline(
    master: dict,
    job: dict,
    *,
    writer_chain: list[LLMProvider],
    verifier_chain: list[LLMProvider],
    stories: list[dict] | None = None,
    guidelines: list[dict] | None = None,
    metrics_sink: dict | None = None,
) -> dict:
    """Run the evidence-led resume pipeline and return renderer-compatible JSON."""
    started = time.time()
    metrics: dict = {"pipeline_version": 2, "stages": []}
    guidelines = guidelines or []
    ledger = build_evidence_ledger(master, stories or [])
    metrics["evidence_items"] = len(ledger)

    stage = time.time()
    plan_provider = "deterministic"
    try:
        raw_plan, plan_provider = _plan_content(master, job, ledger, writer_chain, guidelines)
    except Exception as exc:
        LOG.warning("content planning degraded to deterministic selection: %s", exc)
        raw_plan = {}
        metrics.setdefault("warnings", []).append("content_plan_fallback")
    plan = normalize_content_plan(raw_plan, master, job, ledger)
    _record_stage(metrics, "evidence_selection", stage, provider=plan_provider)

    evidence_ids = selected_evidence_ids(plan, ledger)
    packet = format_evidence_packet(ledger, evidence_ids, max_chars_per_item=650)
    profile = derive_profile(master)

    stage = time.time()
    writer_provider = "deterministic_fallback"
    try:
        writer_system, writer_user = _writer_prompt(
            master, job, profile, plan, packet, guidelines,
        )
        raw_draft, writer_provider = _call_json_chain(
            writer_chain, writer_system, writer_user,
            schema=RESUME_SCHEMA, max_tokens=3000, stage="editorial_write",
        )
    except Exception as exc:
        LOG.error("editorial writing failed; using selected source text: %s", exc)
        raw_draft = _fallback_draft(master, plan)
        metrics.setdefault("warnings", []).append("editorial_write_fallback")
    draft = finalize_resume(_strip_em_dashes(raw_draft), master, plan)
    _record_stage(metrics, "editorial_write", stage, provider=writer_provider)

    grounding_adapters = [DeterministicGroundingAdapter()]
    if any(provider.name != "demo" for provider in verifier_chain):
        grounding_adapters.append(LLMProviderChainGroundingAdapter(verifier_chain))
    engine = GroundingEngine(grounding_adapters)
    stage = time.time()
    first_report = engine.review(draft, plan, ledger)
    first_draft = deepcopy(draft)
    _record_stage(
        metrics, "factual_validation", stage,
        passed=first_report.passed, degraded=first_report.degraded,
        blocking_claims=len(blocking_verdicts(first_report)),
    )

    repaired = False
    final_report = first_report
    if not first_report.passed and not first_report.degraded:
        stage = time.time()
        try:
            repaired_raw, repair_provider = _repair_resume(
                draft, first_report.to_dict(), plan, packet, writer_chain,
            )
            draft = finalize_resume(_strip_em_dashes(repaired_raw), master, plan)
            repaired = True
            final_report = engine.review(draft, plan, ledger)
            if final_report.degraded:
                # The first review already certified most of the editorial
                # draft. If the verifier disappears only during repair, keep
                # those accepted claims and prune the first review's blocked
                # fields below; do not erase all job-specific writing.
                draft = first_draft
                final_report = first_report
                metrics.setdefault("warnings", []).append("repair_verifier_degraded_reverted")
            _record_stage(
                metrics, "factual_repair", stage, provider=repair_provider,
                passed=final_report.passed,
                blocking_claims=len(blocking_verdicts(final_report)),
            )
        except Exception as exc:
            metrics.setdefault("warnings", []).append("grounding_repair_failed")
            LOG.warning("grounding repair failed: %s", exc)

    if final_report.degraded:
        # Semantic validation is the safety net that permits editorial freedom.
        # If every verifier is unavailable, use selected source prose instead
        # of approving an unverifiable rewrite or pruning the resume to empty.
        draft = finalize_resume(_fallback_draft(master, plan), master, plan)
        final_report = GroundingEngine([DeterministicGroundingAdapter()]).review(
            draft, plan, ledger,
        )
        metrics.setdefault("warnings", []).append("semantic_grounding_source_fallback")

    if not final_report.passed:
        fallback_summary = str((master.get("summary_options") or [""])[0])
        draft = prune_unsupported(draft, final_report, fallback_summary)
        draft = finalize_resume(draft, master, plan)
        metrics.setdefault("warnings", []).append("unsupported_claims_pruned")

    metrics["total_seconds"] = round(time.time() - started, 3)
    metrics["content_plan"] = plan
    metrics["audit"] = {
        "evidence_ids": evidence_ids,
        "initial_grounding": first_report.to_dict(),
        "final_grounding": final_report.to_dict(),
        "repair_attempted": repaired,
    }
    if metrics_sink is not None:
        metrics_sink.update(metrics)
    return draft
