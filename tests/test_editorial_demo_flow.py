from pathlib import Path

from src.master_resume import load_master
from src.providers.demo_provider import DemoProvider
from src.reference_loader import load_stories
from src.tailor import Tailor, validate_cover_letter


ROOT = Path(__file__).resolve().parents[1]


def test_demo_provider_runs_the_complete_v2_resume_and_letter_flow():
    master = load_master(ROOT / "demo_data" / "master_data" / "resume.yaml")
    stories = load_stories(ROOT / "demo_data" / "master_data" / "stories")
    provider = DemoProvider(delay=(0, 0))
    tailor = Tailor({
        "tailoring": [provider], "tailoring_premium": [provider],
        "critique": [provider], "cover_letter": [provider], "relinefit": [provider],
    })
    job = {
        "company": "Target Infrastructure",
        "title": "Backend Reliability Engineer",
        "location": "Remote",
        "description": "Own Python data services, retries, observability, and on-call reliability.",
    }

    resume = tailor.tailor_resume(master, job, stories=stories)
    assert resume["experience"]
    assert tailor.last_tailor_metrics["pipeline_version"] == 2
    assert tailor.last_tailor_audit["final_grounding"]["passed"] is True

    letter = tailor.write_cover_letter(
        source=master,
        job=job,
        user={"full_name": "John Doe"},
        bio="I care about reliable systems and understanding failure modes.",
        stories=stories,
        critique=False,
    )
    assert validate_cover_letter(letter) == []
    assert tailor.last_letter_debug["status"] == "ok"
    assert tailor.last_letter_debug["attempts"][0]["grounding"]["passed"] is True
