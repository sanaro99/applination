"""The master resume block must stay byte-stable across jobs.

Part B of the prompt-bloat work relies on providers with automatic prefix
caching (DeepSeek/Mistral/Gemini) reusing the ~14 KB master block on jobs 2..N
of a run. That only works if the master dict is never mutated per-JD — in
particular, _rank_projects_by_jd must reorder a COPY and leave the caller's
projects list untouched. If someone later makes it sort in place, the caching
win silently no-ops with no crash and no failing generation test — this guards
against exactly that.
"""
import json

from src.tailor_graph import _rank_projects_by_jd


def _projects() -> list[dict]:
    return [
        {"name": "ML Demo", "tech": "pytorch", "bullets_all": ["trained a model"]},
        {"name": "Infra Platform", "tech": "kubernetes terraform",
         "bullets_all": ["ran backend services on kubernetes"]},
        {"name": "Frontend App", "tech": "react", "bullets_all": ["built a UI"]},
    ]


def test_rank_does_not_mutate_input_order():
    projects = _projects()
    before = json.dumps(projects)

    ranked = _rank_projects_by_jd(projects, "backend kubernetes services infra")

    # The JD is infra-heavy, so ranking must surface "Infra Platform" first...
    assert ranked[0]["name"] == "Infra Platform"
    # ...but the caller's list is untouched (still canonical order + same bytes).
    assert json.dumps(projects) == before
    assert [p["name"] for p in projects] == ["ML Demo", "Infra Platform", "Frontend App"]


def test_master_dump_is_byte_stable_across_two_jds():
    master = {"skills": ["python"], "projects": _projects()}
    canonical = json.dumps(master, indent=2)

    # Two different JDs must not change the dumped master (ranking is used only
    # to build a separate priority hint, never to mutate the block).
    _rank_projects_by_jd(master.get("projects") or [], "machine learning pytorch")
    _rank_projects_by_jd(master.get("projects") or [], "backend kubernetes infra")

    assert json.dumps(master, indent=2) == canonical
