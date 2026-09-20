from src.layout_policy import repair_orphan_wraps, shrink_to_budget, trim_orphan_wrap
from src.resume_builder import _fit_to_page, layout_diagnostics


def test_one_and_a_half_lines_are_accepted_without_rewrite():
    text = "x" * 198  # 1.5 lines at 132 chars per line
    assert trim_orphan_wrap(text, 132) == text


def test_one_word_orphan_uses_only_safe_cleanup():
    text = "Built a reliable queue in order to successfully process production jobs for teams"
    repaired = trim_orphan_wrap(text, 72, orphan_chars=20)
    assert len(repaired) <= 72
    assert "process production jobs" in repaired
    assert "in order to" not in repaired


def test_no_safe_cleanup_keeps_complete_sentence():
    text = "Built a queue and preserved its critical outcome for customers today"
    assert trim_orphan_wrap(text, 58, orphan_chars=20) == text


def test_shrink_removes_tail_content_without_rewriting_bullets():
    resume = {
        "experience": [{"bullets": ["strong", "middle", "weakest"]}],
        "projects": [{"bullets": ["project strong", "project tail"]}],
    }
    result, removals = shrink_to_budget(
        resume, lambda value: sum(len(e["bullets"]) for key in ("experience", "projects") for e in value[key]), 3,
    )
    remaining = [b for key in ("experience", "projects") for e in result[key] for b in e["bullets"]]
    assert "strong" in remaining
    assert "weakest" not in remaining
    assert removals


def test_renderer_never_expands_from_master_when_page_is_sparse():
    resume = {
        "summary": "Focused engineer.", "skills": [],
        "experience": [{"company": "Acme", "role": "Engineer", "bullets": ["Selected bullet."]}],
        "projects": [], "education": [],
    }
    master = {
        "experience": [{
            "company": "Acme", "role": "Engineer",
            "bullets_all": ["Selected bullet.", "Generic restored bullet."],
        }],
    }
    fitted = _fit_to_page(resume, master=master, base_size=10.0)
    assert fitted["experience"][0]["bullets"] == ["Selected bullet."]
    assert layout_diagnostics(fitted, base_size=10.0)["within_estimated_page"] is True
