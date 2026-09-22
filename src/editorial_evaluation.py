"""End-to-end evaluation harness for the v2 resume and cover-letter pipeline."""
from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any

from .evidence import _recency, build_evidence_ledger
from .grounding import unsupported_numbers_in_text
from .model_evaluation import EvaluationCandidate, MAX_CASES
from .profile import derive_profile
from .prompt_registry import editorial_prompt_manifest
from .providers import get_provider
from .resume_builder import skill_line_capacity
from .tailor import Tailor, validate_cover_letter


@dataclass(frozen=True)
class EditorialEvaluationCase:
    case_id: str
    master_resume: dict
    job: dict
    user: dict
    bio: str
    stories: list[dict]
    expectations: dict
    cloud_safe: bool = False

    @classmethod
    def from_dict(cls, value: dict[str, Any], position: int) -> "EditorialEvaluationCase":
        case_id = str(value.get("id") or f"editorial-{position}").strip()
        master = value.get("master_resume")
        job = value.get("job")
        if not case_id or not isinstance(master, dict) or not isinstance(job, dict):
            raise ValueError("Each editorial case needs id, master_resume, and job objects")
        user = value.get("user") if isinstance(value.get("user"), dict) else {}
        user = {
            "full_name": str(user.get("full_name") or "Evaluation Candidate"),
            "email": str(user.get("email") or "candidate@example.invalid"),
            **user,
        }
        stories = [row for row in value.get("stories") or [] if isinstance(row, dict)]
        expectations = value.get("expectations") if isinstance(value.get("expectations"), dict) else {}
        return cls(
            case_id,
            master,
            job,
            user,
            str(value.get("bio") or ""),
            stories,
            expectations,
            value.get("cloud_safe") is True,
        )


def load_editorial_cases(path: str, *, limit: int = 10) -> list[EditorialEvaluationCase]:
    if not 1 <= limit <= MAX_CASES:
        raise ValueError(f"limit must be between 1 and {MAX_CASES}")
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, list):
        raise ValueError("editorial evaluation cases file must be a JSON array")
    cases = [
        EditorialEvaluationCase.from_dict(value, index + 1)
        for index, value in enumerate(raw[:limit]) if isinstance(value, dict)
    ]
    if not cases:
        raise ValueError("editorial evaluation cases file has no usable cases")
    return cases


def _resume_bullets(resume: dict) -> list[str]:
    return [
        str(bullet)
        for section in ("experience", "projects")
        for entry in resume.get(section) or []
        for bullet in entry.get("bullets") or []
    ]


def score_resume(resume: dict, master: dict, metrics: dict) -> dict:
    ledger = build_evidence_ledger(master)
    evidence_text = "\n".join(item.text for item in ledger)
    bullets = _resume_bullets(resume)
    source_bullets = {
        str(bullet).strip().lower()
        for section in ("experience", "projects")
        for entry in master.get(section) or []
        for bullet in entry.get("bullets_all") or entry.get("bullets") or []
    }
    lengths = [len(value) for value in bullets]
    visible = json.dumps(resume, ensure_ascii=False)
    audit = metrics.get("audit") or {}
    final_grounding = audit.get("final_grounding") or {}
    required_sections = ["summary", "education", "skills", "experience", "projects", "certifications", "awards"]
    expected_sections = [key for key in required_sections if master.get(key) or key == "summary"]
    visible_skills = {
        str(skill).casefold() for group in resume.get("skills") or []
        for skill in group.get("items") or []
    }
    width = skill_line_capacity(float((metrics.get("layout") or {}).get("base_font_size") or 10))

    def ordered(rows: list[dict]) -> bool:
        dates = [_recency(row if isinstance(row, dict) else {"date": str(row)}) for row in rows]
        return dates == sorted(dates, reverse=True)

    return {
        "bullet_count": len(bullets),
        "verbatim_source_bullets": sum(value.strip().lower() in source_bullets for value in bullets),
        "rewritten_bullet_ratio": round(
            1 - (sum(value.strip().lower() in source_bullets for value in bullets) / len(bullets)), 3,
        ) if bullets else 0.0,
        "bullet_lengths": {
            "one_line_preferred": sum(length <= 145 for length in lengths),
            "one_and_half": sum(145 < length <= 198 for length in lengths),
            "two_line": sum(198 < length <= 230 for length in lengths),
            "overlong": sum(length > 230 for length in lengths),
        },
        "unsupported_numbers": unsupported_numbers_in_text(visible, evidence_text),
        "grounding_passed": bool(final_grounding.get("passed", False)),
        "grounding_degraded": bool(final_grounding.get("degraded", False)),
        "selected_experience": [entry.get("company", "") for entry in resume.get("experience") or []],
        "selected_projects": [entry.get("name", "") for entry in resume.get("projects") or []],
        "missing_sections": [key for key in expected_sections if not resume.get(key)],
        "missing_core_skills": [skill for skill in master.get("core_skills") or []
                                if str(skill).casefold() not in visible_skills],
        "skill_rows_over_width": [group.get("group", "") for group in resume.get("skills") or []
                                  if len(f"{group.get('group', '')}: {', '.join(group.get('items') or [])}") > width],
        "two_projects_target_met": len(resume.get("projects") or []) >= min(2, len(master.get("projects") or [])),
        "chronological": {
            key: ordered(resume.get(key) or []) for key in ("experience", "projects", "education", "awards")
        },
        "rendered_pdf_pages": (metrics.get("layout") or {}).get("rendered_pdf_pages"),
        "warnings": list(metrics.get("warnings") or []),
    }


def score_cover_letter(letter: str, master: dict, stories: list[dict], job: dict | None = None) -> dict:
    evidence_text = "\n".join(item.text for item in build_evidence_ledger(master, stories))
    if job:
        evidence_text += "\n" + "\n".join(str(job.get(key) or "") for key in ("company", "title", "description"))
    return {
        "word_count": len((letter or "").split()),
        "paragraph_count": len([part for part in (letter or "").split("\n\n") if part.strip()]),
        "validation_issues": validate_cover_letter(letter or ""),
        "unsupported_numbers": unsupported_numbers_in_text(letter or "", evidence_text),
    }


def score_expectations(resume: dict, letter: str, expectations: dict) -> dict:
    resume_text = json.dumps(resume, ensure_ascii=False).lower()
    all_text = f"{resume_text}\n{letter or ''}".lower()
    required = [str(value).lower() for value in expectations.get("required_phrases") or []]
    forbidden = [str(value).lower() for value in expectations.get("forbidden_phrases") or []]
    companies = {str(entry.get("company") or "").lower() for entry in resume.get("experience") or []}
    projects = {str(entry.get("name") or "").lower() for entry in resume.get("projects") or []}
    required_companies = [str(value).lower() for value in expectations.get("required_experience") or []]
    required_projects = [str(value).lower() for value in expectations.get("required_projects") or []]
    checks = {
        "required_phrases": {value: value in all_text for value in required},
        "forbidden_phrases": {value: value not in all_text for value in forbidden},
        "required_experience": {value: value in companies for value in required_companies},
        "required_projects": {value: value in projects for value in required_projects},
    }
    checks["passed"] = all(
        result for group in checks.values() if isinstance(group, dict) for result in group.values()
    )
    return checks


def run_editorial_evaluation(
    llm_cfg: dict[str, Any],
    candidate: EvaluationCandidate,
    cases: list[EditorialEvaluationCase],
) -> list[dict[str, Any]]:
    """Run the real multi-stage pipeline; batch targets are not interactive adapters."""
    if candidate.mode != "sync":
        raise ValueError("Editorial pipeline evaluation requires a synchronous candidate")
    provider = get_provider(
        candidate.provider, llm_cfg, model_override=candidate.model, thinking="low",
    )
    chains = {
        "tailoring": [provider], "tailoring_premium": [provider],
        "critique": [provider], "cover_letter": [provider], "relinefit": [provider],
    }
    records = []
    for case in cases:
        started = time.monotonic()
        tailor = Tailor(chains, critique_cover_letters=False)
        try:
            resume = tailor.tailor_resume(
                case.master_resume, case.job, stories=case.stories, guidelines=[],
            )
            letter = tailor.write_cover_letter(
                source=case.master_resume,
                job=case.job,
                user=case.user,
                bio=case.bio,
                stories=case.stories,
                profile=derive_profile(case.master_resume),
                critique=False,
            )
            records.append({
                "case_id": case.case_id,
                "candidate": candidate.__dict__,
                "ok": True,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "prompt_versions": editorial_prompt_manifest(),
                "resume": resume,
                "cover_letter": letter,
                "scores": {
                    "resume": score_resume(resume, case.master_resume, tailor.last_tailor_metrics),
                    "cover_letter": score_cover_letter(letter, case.master_resume, case.stories, case.job),
                    "expectations": score_expectations(resume, letter, case.expectations),
                },
                "audit": tailor.last_tailor_audit,
                "cover_letter_debug": tailor.last_letter_debug,
            })
        except Exception as exc:
            records.append({
                "case_id": case.case_id,
                "candidate": candidate.__dict__,
                "ok": False,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "prompt_versions": editorial_prompt_manifest(),
                "error": str(exc)[:500],
            })
    return records
