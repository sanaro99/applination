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

from .evidence import EvidenceItem, format_evidence_packet
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
        packet = format_evidence_packet(ledger)
        valid_ids = {item.id for item in ledger}
        valid_paths = {path for path, _ in _draft_claims(draft)}
        required_paths = set(valid_paths)

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
        user = (
            f"CONTENT PLAN:\n{json.dumps(plan, indent=2)}\n\n"
            f"SOURCE EVIDENCE:\n{packet}\n\n"
            f"DRAFT RESUME:\n{json.dumps(draft, indent=2)}\n\n"
            "Audit the draft. Do not reward keyword overlap unless the evidence supports the claim."
        )
        raw = self.provider.json_call(system, user, max_tokens=2600, schema=GROUNDING_SCHEMA)
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
