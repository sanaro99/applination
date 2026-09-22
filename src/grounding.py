"""Grounding seam for generated career artifacts.

The interface is intentionally small: callers submit a draft, a content plan,
and an evidence ledger and receive one report.  Deterministic and LLM adapters
sit behind the seam so production can combine broad semantic review with
fail-closed checks for identity, citations, and quantitative claims.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import json
import re
from typing import Protocol

from .evidence import EvidenceItem, format_evidence_packet, selected_evidence_ids
from .providers import LLMProvider
from .schemas import GROUNDING_SCHEMA


_NUMBER_RE = re.compile(
    r"(?<![A-Za-z])(?:\$\s*)?\d+(?:[,.]\d+)*(?:\.\d+)?(?:\s*(?:%|\+|x|ms|s|sec|seconds?|"
    r"minutes?|hours?|days?|weeks?|months?|years?|k|m|b))?",
    re.IGNORECASE,
)


def _normal_number(value: str) -> str:
    return re.sub(r"[\s,]", "", value.lower()).rstrip(".")


def numbers_in(text: str) -> set[str]:
    return {_normal_number(match.group(0)) for match in _NUMBER_RE.finditer(text or "")}


def unsupported_numbers_in_text(text: str, evidence_text: str) -> list[str]:
    allowed = numbers_in(evidence_text)
    return sorted(number for number in numbers_in(text) if number not in allowed)


def cover_letter_ledger(
    candidate_ledger: list[EvidenceItem], job: dict,
    selected_ids: list[str] | None = None,
) -> list[EvidenceItem]:
    """Bounded two-source packet for letters: candidate history plus the job."""
    allowed = set(selected_ids or [])
    candidate = [
        EvidenceItem(item.id, item.kind, item.text[:1800 if item.kind == "story" else 900],
                     item.source_id, item.support)
        for item in candidate_ledger if not allowed or item.id in allowed
    ]
    job_text = " | ".join(filter(None, [
        str(job.get("company") or ""), str(job.get("title") or ""),
        str(job.get("location") or ""), str(job.get("description") or "")[:3200],
    ]))
    if job_text:
        candidate.append(EvidenceItem("job.0", "job", job_text, "job"))
    return candidate


@dataclass(frozen=True)
class ClaimVerdict:
    path: str
    claim: str
    support: str
    evidence_ids: list[str]
    action: str
    reason: str
    source: str

    @property
    def blocking(self) -> bool:
        return self.support in {"unsupported", "contradictory"} or self.action in {
            "qualify", "rewrite", "remove",
        }


@dataclass
class GroundingReport:
    verdicts: list[ClaimVerdict] = field(default_factory=list)
    degraded: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.degraded and not any(verdict.blocking for verdict in self.verdicts)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "degraded": self.degraded,
            "notes": list(self.notes),
            "verdicts": [asdict(verdict) for verdict in self.verdicts],
        }


class GroundingAdapter(Protocol):
    def review(self, draft: dict, plan: dict, ledger: list[EvidenceItem]) -> GroundingReport: ...


def _draft_claims(draft: dict) -> list[tuple[str, str]]:
    claims: list[tuple[str, str]] = []
    if draft.get("summary"):
        claims.append(("summary", str(draft["summary"])))
    for section in ("experience", "projects"):
        for i, entry in enumerate(draft.get(section) or []):
            for j, bullet in enumerate(entry.get("bullets") or []):
                claims.append((f"{section}.{i}.bullets.{j}", str(bullet)))
    for i, group in enumerate(draft.get("skills") or []):
        if not isinstance(group, dict):
            continue
        for j, skill in enumerate(group.get("items") or []):
            claims.append((f"skills.{i}.items.{j}", str(skill)))
    return claims


class DeterministicGroundingAdapter:
    """Fail-closed checks for citations and fabricated quantitative facts."""

    def review(self, draft: dict, plan: dict, ledger: list[EvidenceItem]) -> GroundingReport:
        # Selection determines what the writer should emphasize, not what is
        # true. Review against the full ledger so a truthful source fact that
        # survived a rewrite is not mislabeled as fabricated merely because a
        # planner omitted its ID.
        evidence_text = "\n".join(item.text for item in ledger)
        allowed_numbers = numbers_in(evidence_text)
        verdicts: list[ClaimVerdict] = []

        for path, claim in _draft_claims(draft):
            extras = sorted(number for number in numbers_in(claim) if number not in allowed_numbers)
            if not extras:
                continue
            verdicts.append(ClaimVerdict(
                path=path,
                claim=claim,
                support="unsupported",
                evidence_ids=[],
                action="rewrite",
                reason=f"Quantitative detail is absent from selected source evidence: {', '.join(extras)}.",
                source="deterministic",
            ))
        return GroundingReport(verdicts=verdicts)


class LLMGroundingAdapter:
    """Semantic claim reviewer implemented by an existing provider adapter."""

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    def review(self, draft: dict, plan: dict, ledger: list[EvidenceItem]) -> GroundingReport:
        is_letter = plan.get("artifact_kind") == "cover_letter"
        selected = set(selected_evidence_ids(plan, ledger)) if plan else set()
        if selected:
            selected.update(item.id for item in ledger if item.kind == "job")
        packet = format_evidence_packet(
            [item for item in ledger if item.kind != "job"], selected,
            max_chars_per_item=1800 if is_letter else 900,
        )
        if is_letter:
            packet += "\n" + format_evidence_packet(
                [item for item in ledger if item.kind == "job"], max_chars_per_item=3200,
            )
        valid_ids = {item.id for item in ledger if not selected or item.id in selected}
        direct_skills = {
            item.text.split(":", 1)[-1].strip().casefold()
            for item in ledger if item.kind == "skill" and item.support == "direct"
        }
        review_claims = [
            (path, claim) for path, claim in _draft_claims(draft)
            if not (path.startswith("skills.") and claim.casefold() in direct_skills)
        ]
        if is_letter and draft.get("summary"):
            paragraphs = [part.strip() for part in re.split(r"\n\s*\n", str(draft["summary"])) if part.strip()]
            if len(paragraphs) > 1:
                review_claims = [(f"summary.{index}", part) for index, part in enumerate(paragraphs)]
        valid_paths = {path for path, _ in review_claims}
        required_paths = set(valid_paths)
        if not review_claims:
            return GroundingReport()

        system = (
            "You are a factual editor for resumes. Audit every material claim against the "
            "numbered source evidence. Split compound bullets into atomic claims and emit a "
            "verdict for each claim, reusing the bullet path when necessary.\n\n"
            "Support labels:\n"
            "- direct: explicitly present in cited evidence.\n"
            "- entailed: faithful paraphrase or combination that adds no material fact.\n"
            "- adjacent: a transferable relationship, not proof the candidate used a new tool.\n"
            "- unsupported: adds an uncited tool, metric, scope, responsibility, outcome, or domain.\n"
            "- contradictory: conflicts with the evidence.\n\n"
            "A plain resume skill must be direct or faithfully entailed. Adjacent knowledge is "
            "acceptable only when the visible claim itself says familiarity, transferable "
            "foundations, or equivalent, and never implies hands-on use. "
            "Merging, splitting, compressing, and reordering source facts are allowed. Every "
            "accepted verdict must cite valid evidence IDs. Set action=accept only for safe final "
            "wording; otherwise choose qualify, rewrite, or remove. Return JSON only."
        )
        if is_letter:
            system = (
                "You are a factual editor for cover letters. Split each paragraph into atomic "
                "candidate and job-description facts, using the summary path for every verdict. "
                "Candidate experience, skills, metrics, employers, and outcomes require candidate "
                "evidence IDs; job-description facts require job IDs. A job fact can explain interest "
                "or fit but cannot prove that the candidate has used the employer's tools. "
                "Faithful paraphrase and clearly qualified transfer are allowed; invented hands-on "
                "experience is not. Audit every material candidate claim and every material company "
                "claim. Statements of interest and reasoned fit are editorial judgments, not "
                "claims that a source must say verbatim: accept them when the cited candidate "
                "experience and job requirements support the comparison. Do not mark a grounded "
                "fit statement 'qualify' just to soften tone; reserve that action for wording that "
                "actually implies an unsupported fact. Every accepted verdict needs a relevant "
                "citation. Return one JSON object "
                "with verdicts and passed keys, not a bare array. In each verdict, make claim a "
                "brief identifying fragment (at most 12 words) and reason similarly brief; do not "
                "repeat whole paragraphs. Return JSON only."
            )
        def audit(claims: list[tuple[str, str]], max_tokens: int) -> object:
            user = (
                f"SOURCE EVIDENCE:\n{packet}\n\n"
                f"CLAIMS TO REVIEW ({'COVER LETTER' if is_letter else 'RESUME'}):\n"
                f"{json.dumps([{'path': path, 'text': claim} for path, claim in claims], indent=2)}\n\n"
                "Audit every listed claim. Keep the exact paths. Do not reward keyword overlap "
                "unless the evidence supports the claim."
            )
            return self.provider.json_call(system, user, max_tokens=max_tokens, schema=GROUNDING_SCHEMA)

        try:
            raw = audit(review_claims, 2600)
        except Exception:
            if not is_letter or len(review_claims) <= 1:
                raise
            # A long cover letter can make one all-claims JSON response
            # malformed. Review its short paragraphs independently; every
            # paragraph still needs a complete verdict or the audit fails.
            raw = {"verdicts": []}
            for claim in review_claims:
                part = audit([claim], 1400)
                raw["verdicts"].extend(part if isinstance(part, list) else part.get("verdicts") or [])
        if isinstance(raw, list):
            raw = {"verdicts": raw}
        if not isinstance(raw, dict):
            raise ValueError("semantic verifier returned a non-object response")
        # Models sometimes answer only the first claim. Retry only absent
        # paths in small batches, instead of approving them or rewriting the
        # entire resume from scratch.
        returned_paths = {
            str(row.get("path") or "") for row in raw.get("verdicts") or []
            if isinstance(row, dict)
        }
        missing_claims = [row for row in review_claims if row[0] not in returned_paths]
        batch_size = 1 if is_letter else 4
        for offset in range(0, len(missing_claims), batch_size):
            batch = missing_claims[offset:offset + batch_size]
            try:
                part = audit(batch, 1600)
                raw.setdefault("verdicts", []).extend(
                    part if isinstance(part, list) else part.get("verdicts") or []
                )
            except Exception:
                # Missing paths become blocking verdicts below. A transient
                # failure cannot silently certify generated claims.
                continue
        verdicts: list[ClaimVerdict] = []
        for raw_verdict in raw.get("verdicts") or [] if isinstance(raw, dict) else []:
            if not isinstance(raw_verdict, dict):
                continue
            path = str(raw_verdict.get("path") or "")
            if path not in valid_paths:
                continue
            evidence_ids = [
                str(value) for value in raw_verdict.get("evidence_ids") or []
                if str(value) in valid_ids
            ]
            support = str(raw_verdict.get("support") or "unsupported")
            action = str(raw_verdict.get("action") or "rewrite")
            # A supposedly accepted claim with no real citation is not grounded.
            if action == "accept" and support in {"direct", "entailed", "adjacent"} and not evidence_ids:
                support, action = "unsupported", "rewrite"
            if is_letter and action == "accept" and evidence_ids and all(
                value.startswith("job.") for value in evidence_ids
            ) and re.search(
                r"\b(?:I|we)\s+(?:(?:have|had)\s+)?(?:built|shipped|led|designed|implemented|developed|"
                r"engineered|managed|maintained|used|delivered|deployed|created|achieved|"
                r"reduced|increased|worked|have\s+experience)\b|"
                r"\b(?:my|our)\s+(?:experience|expertise|work|skills|projects|responsibilities)\b|"
                r"^\s*(?:built|shipped|led|designed|implemented|developed|engineered|"
                r"managed|maintained)\b",
                str(raw_verdict.get("claim") or ""), re.IGNORECASE,
            ):
                support, action = "unsupported", "rewrite"
            if (
                action == "accept"
                and support == "adjacent"
                and not re.search(
                    r"\b(?:adjacent|familiar(?:ity)?|transferable|foundations?|"
                    r"related knowledge|exposure)\b",
                    str(raw_verdict.get("claim") or ""),
                    re.IGNORECASE,
                )
            ):
                action = "qualify"
            verdicts.append(ClaimVerdict(
                path=path,
                claim=str(raw_verdict.get("claim") or ""),
                support=support,
                evidence_ids=evidence_ids,
                action=action,
                reason=str(raw_verdict.get("reason") or ""),
                source=f"llm:{self.provider.name}",
            ))
        reviewed_paths = {verdict.path for verdict in verdicts}
        for path in sorted(required_paths - reviewed_paths):
            verdicts.append(ClaimVerdict(
                path=path,
                claim="",
                support="unsupported",
                evidence_ids=[],
                action="rewrite",
                reason="Semantic verifier did not return a verdict for this generated field.",
                source=f"llm:{self.provider.name}",
            ))
        return GroundingReport(verdicts=verdicts)


class LLMProviderChainGroundingAdapter:
    """Try provider adapters in order and use the first successful review."""

    def __init__(self, providers: list[LLMProvider]):
        self.providers = list(providers)

    def review(self, draft: dict, plan: dict, ledger: list[EvidenceItem]) -> GroundingReport:
        last_error: Exception | None = None
        for provider in self.providers:
            try:
                return LLMGroundingAdapter(provider).review(draft, plan, ledger)
            except Exception as exc:
                last_error = exc
        reason = str(last_error or "No grounding provider configured")[:180]
        return GroundingReport(
            degraded=True,
            notes=[f"Semantic grounding unavailable: {reason}"],
            verdicts=[
                ClaimVerdict(
                    path=path,
                    claim=claim,
                    support="unsupported",
                    evidence_ids=[],
                    action="rewrite",
                    reason="Claim could not be semantically verified.",
                    source="llm:unavailable",
                )
                for path, claim in _draft_claims(draft)
            ],
        )


class GroundingEngine:
    """Deep grounding module combining all configured review adapters."""

    def __init__(self, adapters: list[GroundingAdapter]):
        self.adapters = list(adapters)

    def review(self, draft: dict, plan: dict, ledger: list[EvidenceItem]) -> GroundingReport:
        combined = GroundingReport()
        for adapter in self.adapters:
            try:
                report = adapter.review(draft, plan, ledger)
            except Exception as exc:  # provider failure must not approve claims
                combined.degraded = True
                combined.notes.append(f"{type(adapter).__name__} failed: {str(exc)[:180]}")
                combined.verdicts.extend(
                    ClaimVerdict(
                        path=path,
                        claim=claim,
                        support="unsupported",
                        evidence_ids=[],
                        action="rewrite",
                        reason="Claim could not be reviewed by the configured grounding adapter.",
                        source=type(adapter).__name__,
                    )
                    for path, claim in _draft_claims(draft)
                )
                continue
            combined.verdicts.extend(report.verdicts)
            combined.degraded = combined.degraded or report.degraded
            combined.notes.extend(report.notes)
        return combined


def blocking_verdicts(report: GroundingReport) -> list[ClaimVerdict]:
    return [verdict for verdict in report.verdicts if verdict.blocking]


def prune_unsupported(draft: dict, report: GroundingReport, fallback_summary: str = "") -> dict:
    """Last-resort deterministic repair after a model repair still fails review."""
    out = deepcopy(draft)
    paths = {verdict.path for verdict in blocking_verdicts(report)}
    if "summary" in paths and fallback_summary:
        out["summary"] = fallback_summary

    for section in ("experience", "projects"):
        removals: dict[int, list[int]] = {}
        prefix = section + "."
        for path in paths:
            if not path.startswith(prefix):
                continue
            match = re.fullmatch(rf"{section}\.(\d+)\.bullets\.(\d+)", path)
            if match:
                removals.setdefault(int(match.group(1)), []).append(int(match.group(2)))
        for entry_index, bullet_indices in removals.items():
            entries = out.get(section) or []
            if entry_index >= len(entries):
                continue
            bullets = entries[entry_index].get("bullets") or []
            for bullet_index in sorted(set(bullet_indices), reverse=True):
                if bullet_index < len(bullets):
                    bullets.pop(bullet_index)
        out[section] = [entry for entry in out.get(section) or [] if entry.get("bullets")]

    skill_removals: dict[int, list[int]] = {}
    for path in paths:
        match = re.fullmatch(r"skills\.(\d+)\.items\.(\d+)", path)
        if match:
            skill_removals.setdefault(int(match.group(1)), []).append(int(match.group(2)))
    for group_index, item_indices in skill_removals.items():
        groups = out.get("skills") or []
        if group_index >= len(groups):
            continue
        values = groups[group_index].get("items") or []
        for item_index in sorted(set(item_indices), reverse=True):
            if item_index < len(values):
                values.pop(item_index)
    out["skills"] = [group for group in out.get("skills") or [] if group.get("items")]
    return out
