from src.evidence import build_evidence_ledger, default_content_plan
from src.grounding import (
    DeterministicGroundingAdapter,
    ClaimVerdict,
    GroundingReport,
    LLMGroundingAdapter,
    LLMProviderChainGroundingAdapter,
    cover_letter_ledger,
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


def test_cover_letter_grounding_separates_job_facts_from_candidate_experience():
    class _Verifier(LLMProvider):
        name = "cover-verifier"

        def text_call(self, system, user, max_tokens=1000):
            raise AssertionError

        def json_call(self, system, user, max_tokens=2000, *, schema=None):
            assert "job-description facts" in system
            assert "reasoned fit are editorial judgments" in system
            assert "Acme is building a payments platform" in user
            return {"passed": True, "verdicts": [
                {"path": "summary", "claim": "I built a payments platform",
                 "support": "direct", "evidence_ids": ["job.0"],
                 "action": "accept", "reason": "Found in job"},
            ]}

    ledger = cover_letter_ledger(
        build_evidence_ledger(MASTER),
        {"company": "Acme", "title": "Engineer", "description": "Acme is building a payments platform"},
    )
    report = LLMGroundingAdapter(_Verifier()).review(
        {"summary": "I built a payments platform"},
        {"artifact_kind": "cover_letter"}, ledger,
    )
    assert not report.passed
    assert report.verdicts[0].support == "unsupported"


def test_semantic_review_does_not_respend_tokens_on_exact_source_skills():
    class _Capture(LLMProvider):
        name = "capture"

        def text_call(self, system, user, max_tokens=1000):
            raise AssertionError

        def json_call(self, system, user, max_tokens=2000, *, schema=None):
            assert '"path": "skills.0.items.0"' not in user
            assert '"path": "summary"' in user
            return {"passed": True, "verdicts": [{
                "path": "summary", "claim": "Backend engineer", "support": "direct",
                "evidence_ids": ["summary.0"], "action": "accept", "reason": "Source-backed",
            }]}

    report = LLMGroundingAdapter(_Capture()).review(
        {"summary": "Backend engineer", "skills": [{"group": "Languages", "items": ["Python"]}]},
        {}, build_evidence_ledger(MASTER),
    )
    assert report.passed


def test_cover_letter_can_cite_a_company_fact_from_the_job():
    class _Verifier(LLMProvider):
        name = "job-verifier"

        def text_call(self, system, user, max_tokens=1000):
            raise AssertionError

        def json_call(self, system, user, max_tokens=2000, *, schema=None):
            return {"passed": True, "verdicts": [{
                "path": "summary", "claim": "Acme is building a payments platform",
                "support": "direct", "evidence_ids": ["job.0"],
                "action": "accept", "reason": "The job says so",
            }]}

    ledger = cover_letter_ledger(build_evidence_ledger(MASTER), {
        "company": "Acme", "title": "Engineer", "description": "Acme is building a payments platform",
    })
    report = LLMGroundingAdapter(_Verifier()).review(
        {"summary": "Acme is building a payments platform"},
        {"artifact_kind": "cover_letter"}, ledger,
    )
    assert report.passed


def test_personal_interest_in_a_cited_job_mission_is_not_candidate_work_history():
    class _Verifier(LLMProvider):
        name = "interest-verifier"

        def text_call(self, system, user, max_tokens=1000):
            raise AssertionError

        def json_call(self, system, user, max_tokens=2000, *, schema=None):
            return {"verdicts": [{
                "path": "summary", "claim": "I am drawn to Acme's payments mission",
                "support": "entailed", "evidence_ids": ["job.0"],
                "action": "accept", "reason": "Job mission is stated; interest is personal",
            }]}

    ledger = cover_letter_ledger(build_evidence_ledger(MASTER), {
        "company": "Acme", "title": "Engineer", "description": "Acme builds payment services",
    })
    report = LLMGroundingAdapter(_Verifier()).review(
        {"summary": "I am drawn to Acme's payments mission."},
        {"artifact_kind": "cover_letter"}, ledger,
    )
    assert report.passed


def test_complete_bare_verdict_array_is_still_audited():
    class _ArrayVerifier(LLMProvider):
        name = "array-verifier"

        def text_call(self, system, user, max_tokens=1000):
            raise AssertionError

        def json_call(self, system, user, max_tokens=2000, *, schema=None):
            return [{
                "path": "summary", "claim": "Acme is building payments",
                "support": "direct", "evidence_ids": ["job.0"],
                "action": "accept", "reason": "Job description states this",
            }]

    ledger = cover_letter_ledger(build_evidence_ledger(MASTER), {
        "company": "Acme", "title": "Engineer", "description": "Acme is building payments",
    })
    report = LLMGroundingAdapter(_ArrayVerifier()).review(
        {"summary": "Acme is building payments"},
        {"artifact_kind": "cover_letter"}, ledger,
    )
    assert report.passed


def test_resume_verifier_rechecks_only_missing_paths():
    class _PartialVerifier(LLMProvider):
        name = "partial-verifier"

        def __init__(self):
            self.calls = 0

        def text_call(self, system, user, max_tokens=1000):
            raise AssertionError

        def json_call(self, system, user, max_tokens=2000, *, schema=None):
            self.calls += 1
            if self.calls == 1:
                assert '"path": "summary"' in user
                return {"verdicts": [{
                    "path": "summary", "claim": "Backend engineer", "support": "direct",
                    "evidence_ids": ["summary.0"], "action": "accept", "reason": "Source-backed",
                }]}
            assert '"path": "summary"' not in user
            assert '"path": "experience.0.bullets.0"' in user
            return {"verdicts": [{
                "path": "experience.0.bullets.0", "claim": "Diagnosed retry contention",
                "support": "direct", "evidence_ids": ["experience.0.bullet.0"],
                "action": "accept", "reason": "Source-backed",
            }]}

    provider = _PartialVerifier()
    report = LLMGroundingAdapter(provider).review({
        "summary": "Backend engineer", "skills": [], "projects": [],
        "experience": [{"bullets": ["Diagnosed retry contention."]}],
    }, {}, build_evidence_ledger(MASTER))
    assert report.passed
    assert provider.calls == 2


def test_cover_letter_malformed_full_audit_retries_each_paragraph():
    class _ParagraphVerifier(LLMProvider):
        name = "paragraph-verifier"

        def __init__(self):
            self.calls = 0

        def text_call(self, system, user, max_tokens=1000):
            raise AssertionError

        def json_call(self, system, user, max_tokens=2000, *, schema=None):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("malformed JSON")
            index = self.calls - 2
            evidence_id = "experience.0.bullet.0" if index == 1 else "job.0"
            return {"verdicts": [{
                "path": f"summary.{index}",
                "claim": "Diagnosed retries" if index == 1 else "Acme builds payments",
                "support": "direct", "evidence_ids": [evidence_id],
                "action": "accept", "reason": "Cited source",
            }]}

    provider = _ParagraphVerifier()
    ledger = cover_letter_ledger(build_evidence_ledger(MASTER), {
        "company": "Acme", "title": "Engineer",
        "description": "Acme builds payments and is hiring an engineer.",
    })
    report = LLMGroundingAdapter(provider).review({
        "summary": "Acme builds payments.\n\nI diagnosed retry contention.\n\nAcme is hiring an engineer.",
    }, {"artifact_kind": "cover_letter", "summary_evidence_ids": ["experience.0.bullet.0"]}, ledger)
    assert report.passed
    assert provider.calls == 4


def test_cover_letter_verifier_sees_late_details_from_the_anchor_story():
    class _Verifier(LLMProvider):
        name = "story-verifier"

        def text_call(self, system, user, max_tokens=1000):
            raise AssertionError

        def json_call(self, system, user, max_tokens=2000, *, schema=None):
            assert "known-good library" in user
            return {"passed": True, "verdicts": [{
                "path": "summary", "claim": "I used a known-good library",
                "support": "direct", "evidence_ids": ["story.0"],
                "action": "accept", "reason": "The story states it",
            }]}

    story = {"title": "Automation", "one_liner": "Built workflows",
             "body": "Context " + ("x" * 950) + " known-good library"}
    candidate = build_evidence_ledger(MASTER, [story])
    ledger = cover_letter_ledger(candidate, {"company": "Acme", "title": "Engineer"}, ["story.0"])
    report = LLMGroundingAdapter(_Verifier()).review(
        {"summary": "I used a known-good library"},
        {"artifact_kind": "cover_letter", "summary_evidence_ids": ["story.0"]}, ledger,
    )
    assert report.passed
