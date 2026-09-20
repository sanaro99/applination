from src.evidence import build_evidence_ledger, default_content_plan
from src.grounding import (
    DeterministicGroundingAdapter,
    ClaimVerdict,
    GroundingReport,
    LLMProviderChainGroundingAdapter,
    prune_unsupported,
    unsupported_numbers_in_text,
)
from src.providers.base import LLMProvider

from tests.test_evidence_pipeline import MASTER


def test_deterministic_grounding_rejects_invented_metric():
    ledger = build_evidence_ledger(MASTER)
    plan = default_content_plan(MASTER, {"title": "Backend Engineer"}, ledger)
    draft = {
        "summary": "Backend engineer.", "skills": [], "projects": [],
        "experience": [{"bullets": ["Reduced failed jobs by 99% after redesigning retries."]}],
    }
    report = DeterministicGroundingAdapter().review(draft, plan, ledger)
    assert not report.passed
    assert report.verdicts[0].path == "experience.0.bullets.0"
    assert "99%" in report.verdicts[0].reason


def test_numbers_can_be_rephrased_but_not_created():
    evidence = "Reduced failed jobs by 40% after isolating retries."
    assert unsupported_numbers_in_text("Cut failures 40%.", evidence) == []
    assert unsupported_numbers_in_text("Cut failures 41%.", evidence) == ["41%"]


def test_last_resort_pruning_removes_only_the_flagged_bullet():
    resume = {
        "summary": "Supported summary.", "skills": [], "projects": [],
        "experience": [{"bullets": ["Safe bullet.", "Invented 99% metric."]}],
    }
    report = GroundingReport(verdicts=[ClaimVerdict(
        path="experience.0.bullets.1", claim="Invented 99% metric.",
        support="unsupported", evidence_ids=[], action="remove",
        reason="Metric absent.", source="test",
    )])
    result = prune_unsupported(resume, report)
    assert result["experience"][0]["bullets"] == ["Safe bullet."]


class _BrokenVerifier(LLMProvider):
    name = "broken-verifier"

    def text_call(self, system: str, user: str, max_tokens: int = 1000) -> str:
        raise RuntimeError("offline")

    def json_call(self, system: str, user: str, max_tokens: int = 2000, *, schema=None):
        raise RuntimeError("offline")


def test_semantic_verifier_failure_is_fail_closed():
    draft = {
        "summary": "Rewritten claim.",
        "skills": [{"group": "Related Knowledge", "items": ["MongoDB"]}],
        "experience": [], "projects": [],
    }
    report = LLMProviderChainGroundingAdapter([_BrokenVerifier()]).review(
        draft, {}, build_evidence_ledger(MASTER),
    )
    assert report.degraded is True
    assert report.passed is False
    assert {verdict.path for verdict in report.verdicts} == {"summary", "skills.0.items.0"}
