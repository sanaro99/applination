"""Unit tests for src/line_fitter.py — pure-Python, no LLM calls."""
from __future__ import annotations

import pytest

from src import line_fitter as lf
from src.line_fitter import (
    DOUBLE_MAX,
    DOUBLE_MIN,
    FORBIDDEN_HI,
    FORBIDDEN_LO,
    SINGLE_MAX,
    SINGLE_MIN,
    SINGLE_TARGET,
    classify,
    configure_for_font,
    fit_bullets_to_bands,
    is_clean,
    is_underfilled_single,
)


@pytest.fixture(autouse=True)
def _pin_font():
    """Pin the line-fit bands to the project default (10pt) so tests are
    deterministic regardless of prior reconfiguration. The bands are font-aware
    (see configure_for_font); these tests assert against the 10pt calibration."""
    configure_for_font(10.0)
    yield
    configure_for_font(10.0)


def _pad(prefix: str, target_len: int) -> str:
    """Grow `prefix` with realistic filler to ~target_len chars, ending cleanly.

    Keeps the leading words (which drive master-variant matching) intact while
    hitting an exact length band. Used so fixtures track the font-aware bands
    instead of hard-coded character counts."""
    s = prefix.rstrip(" .")
    tail = " across regional teams and production systems with measurable impact"
    while len(s) + 1 < target_len:
        s += tail
    return s[:target_len - 1].rstrip(" ,;") + "."


# Representative lengths inside each 10pt band.
_FORBIDDEN_LEN = (FORBIDDEN_LO + FORBIDDEN_HI) // 2   # ~165
_DOUBLE_LEN = (DOUBLE_MIN + DOUBLE_MAX) // 2          # ~231
_SINGLE_LEN = SINGLE_MAX - 4                          # ~121 (well-filled single)
_UNDERFILLED_LEN = SINGLE_MIN + 8                     # ~87 (clean single, under target)


# ---------------------------------------------------------------------------
# classify() basics — boundaries derived from the active (font-aware) bands
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("length,expected", [
    (50, "short"),
    (SINGLE_MIN - 1, "short"),
    (SINGLE_MIN, "single"),
    (110, "single"),
    (SINGLE_MAX, "single"),
    (FORBIDDEN_LO, "forbidden"),
    (_FORBIDDEN_LEN, "forbidden"),
    (FORBIDDEN_HI, "forbidden"),
    (DOUBLE_MIN, "double"),
    (_DOUBLE_LEN, "double"),
    (DOUBLE_MAX, "double"),
    (DOUBLE_MAX + 1, "overlong"),
    (400, "overlong"),
])
def test_classify_bands(length, expected):
    assert classify(length) == expected


def test_is_clean():
    assert is_clean(110)            # single
    assert is_clean(_DOUBLE_LEN)   # double
    assert not is_clean(_FORBIDDEN_LEN)
    assert not is_clean(DOUBLE_MAX + 100)


# ---------------------------------------------------------------------------
# Single-line fill floor (SINGLE_TARGET / is_underfilled_single)
# ---------------------------------------------------------------------------

def test_single_target_is_88_percent_fill():
    assert SINGLE_TARGET == round(lf.LINE_CHARS * 0.88)
    # Ordering invariant: SINGLE_MIN < SINGLE_TARGET <= SINGLE_MAX.
    assert SINGLE_MIN < SINGLE_TARGET <= SINGLE_MAX


@pytest.mark.parametrize("length,expected", [
    (SINGLE_MIN - 1, False),     # too short to count as a single at all
    (SINGLE_MIN, True),          # clean single but under-filled
    (SINGLE_TARGET - 1, True),   # just under target -> under-filled
    (SINGLE_TARGET, False),      # at target -> well-filled
    (SINGLE_MAX, False),         # full line
    (FORBIDDEN_LO, False),       # forbidden, not a single at all
])
def test_is_underfilled_single(length, expected):
    assert is_underfilled_single(length) is expected
    # An under-filled single must still render cleanly (it's a soft signal).
    if expected:
        assert classify(length) == "single"


def test_underfilled_single_with_master_flagged_extend():
    """A clean but under-filled single line that HAS a master pool to draw on
    is flagged mode='extend' so the rescue can fill it toward a full line."""
    tailored = {
        "experience": [{
            "company": "UBS", "role": "Sr. Software Engineer",
            "bullets": [_pad("Built internal tooling for the platform team", _UNDERFILLED_LEN)],
        }],
        "projects": [],
    }
    master = {"experience": [{
        "company": "UBS", "role": "Sr. Software Engineer",
        "bullets_all": [_pad("Built internal tooling for the platform team "
                             "automating releases", _DOUBLE_LEN)],
    }], "projects": []}
    _, stats = fit_bullets_to_bands(tailored, master)
    extend_flags = [f for f in stats["flagged_for_llm"] if f.get("mode") == "extend"]
    assert len(extend_flags) == 1, f"under-filled single not flagged extend: {stats}"


def test_underfilled_single_without_master_not_flagged():
    """No master pool -> do NOT flag for extend (avoids padding from nothing)."""
    tailored = {
        "experience": [{
            "company": "Nowhere", "role": "Unknown Role",
            "bullets": [_pad("Built internal tooling for the platform team", _UNDERFILLED_LEN)],
        }],
        "projects": [],
    }
    master = {"experience": [], "projects": []}
    _, stats = fit_bullets_to_bands(tailored, master)
    assert not [f for f in stats["flagged_for_llm"] if f.get("mode") == "extend"]


def test_wellfilled_single_not_flagged():
    """A single already at/above the fill target is left alone."""
    tailored = {
        "experience": [{
            "company": "UBS", "role": "Sr. Software Engineer",
            "bullets": [_pad("Built internal tooling for the platform team", _SINGLE_LEN)],
        }],
        "projects": [],
    }
    master = {"experience": [{
        "company": "UBS", "role": "Sr. Software Engineer",
        "bullets_all": [_pad("Built internal tooling for the platform team x", _DOUBLE_LEN)],
    }], "projects": []}
    _, stats = fit_bullets_to_bands(tailored, master)
    assert not stats["flagged_for_llm"], f"well-filled single should not be flagged: {stats}"


# ---------------------------------------------------------------------------
# fit_bullets_to_bands() — synthetic resume with realistic master pool
# ---------------------------------------------------------------------------

@pytest.fixture
def master():
    """Master with bullets_all variants in the double-line band, prefixes
    chosen to match the forbidden tailored bullets below."""
    variants = [
        _pad("Architected RAG chatbot on Azure AI Search indexing 50K+ team emails over 5 years "
             "surfacing automated incident diagnoses", _DOUBLE_LEN),
        _pad("Engineered config-driven monitoring dashboard with dynamic UI generation aggregating "
             "server health and ServiceNow ticket data", _DOUBLE_LEN),
        _pad("Mentored junior engineers through transition into high-stakes production environments "
             "authoring onboarding docs adopted widely", _DOUBLE_LEN),
    ]
    return {
        "experience": [{
            "company": "UBS",
            "role": "Sr. Software Engineer",
            "bullets_all": variants,
        }],
        "projects": [{
            "name": "GenASL",
            "bullets_all": [
                _pad("End-to-end AI pipeline generating Picture-in-Picture American Sign Language "
                     "overlays for YouTube videos translating transcripts", _DOUBLE_LEN),
            ],
        }],
    }


@pytest.fixture
def tailored():
    """7 bullets: 5 experience in the forbidden zone (3 with master matches),
    2 single-line project bullets to keep."""
    return {
        "experience": [{
            "company": "UBS",
            "role": "Sr. Software Engineer",
            "bullets": [
                # forbidden; matches "Architected RAG..." master variant
                _pad("Architected RAG chatbot on Azure AI Search indexing 50K+ team emails "
                     "for incident diagnosis", _FORBIDDEN_LEN),
                # forbidden; matches "Engineered config-driven..." master variant
                _pad("Engineered config-driven monitoring dashboard with dynamic UI generation "
                     "aggregating server health", _FORBIDDEN_LEN),
                # forbidden; matches "Mentored junior..." master variant
                _pad("Mentored junior engineers through transition into high-stakes production "
                     "environments", _FORBIDDEN_LEN),
                # forbidden; NO master match (off-topic), no safe trim — must
                # stay intact ending on "constraints."
                "Partnered with product and operations stakeholders to scope, design, and "
                "ship AI tooling within regulatory, cost, and latency constraints.",
                # forbidden; NO master match — should TRIM or flag
                _pad("Led AutoFlow LLM platform converting natural language to automation "
                     "workflows", _FORBIDDEN_LEN),
            ],
        }],
        "projects": [{
            "name": "GenASL",
            "bullets": [
                # single (keep)
                _pad("Clip-chaining system mapping ASL gloss to 2K+ video assets", _SINGLE_LEN),
                # single (keep)
                _pad("FAISS embedding index powering smooth concatenated playback", _SINGLE_LEN),
            ],
        }],
    }


def test_fit_eliminates_forbidden_bullets(tailored, master):
    out, stats = fit_bullets_to_bands(tailored, master)

    # Every bullet should be in a clean band OR flagged for LLM rescue.
    leftover_forbidden = 0
    for section in ("experience", "projects"):
        for entry in out[section]:
            for b in entry["bullets"]:
                if classify(len(b)) == "forbidden":
                    leftover_forbidden += 1

    # Count only "compress" flags (forbidden/overlong); "extend" flags are
    # under-filled clean singles, a separate concern.
    flagged_compress = sum(
        1 for f in stats["flagged_for_llm"] if f.get("mode", "compress") == "compress"
    )
    # Everything in the forbidden zone should be either fixed or flagged.
    # No silently-broken bullets should remain.
    assert leftover_forbidden == flagged_compress, (
        f"Forbidden bullets remain: {leftover_forbidden} unflagged "
        f"(stats: {stats})"
    )


def test_master_expansion_used_for_topic_matched_bullets(tailored, master):
    out, stats = fit_bullets_to_bands(tailored, master)

    # Should swap in the 3 UBS experience double-line variants + 1 GenASL.
    assert stats["expanded"] >= 3, (
        f"Expected ≥3 master substitutions, got {stats['expanded']}. "
        f"Stats: {stats}"
    )

    # Verify the actual bullets were replaced with longer master content
    sr_swe_bullets = out["experience"][0]["bullets"]
    double_count = sum(1 for b in sr_swe_bullets if DOUBLE_MIN <= len(b) <= DOUBLE_MAX)
    assert double_count >= 3, (
        f"Expected ≥3 bullets in double band after fit, got {double_count}. "
        f"Lengths: {[len(b) for b in sr_swe_bullets]}"
    )


def test_unmatched_forbidden_bullet_is_left_intact(tailored, master):
    """SAFETY: a forbidden bullet with no master match and no safe trim
    should be KEPT AS-IS (not truncated mid-sentence). Wrap-waste is OK;
    broken sentences are not."""
    out, stats = fit_bullets_to_bands(tailored, master)

    # The "Partnered with product and ops..." bullet has no master variant
    # and no parenthetical / qualifier to safely drop. It must remain
    # complete (still ends with "constraints.") and may be flagged for LLM.
    partnered = next(
        (b for b in out["experience"][0]["bullets"] if b.lower().startswith("partnered")),
        None,
    )
    assert partnered is not None
    # No mid-sentence truncation — the original ended with "constraints."
    assert partnered.rstrip(".").endswith("constraints"), (
        f"Forbidden bullet was truncated mid-sentence: {partnered!r}"
    )


def test_overlong_bullet_uses_safe_trim_or_is_flagged():
    """An overlong bullet with a droppable parenthetical can be safely
    trimmed. If no safe trim helps, it's flagged for LLM rescue — never
    truncated by dropping trailing clauses."""
    tailored = {
        "experience": [{
            "company": "UBS",
            "role": "Sr. Software Engineer",
            "bullets": [
                # 270+ chars with a trailing parenthetical we can safely drop.
                "Built shift handover platform tracking deliverables and workload across "
                "regional shifts (running on Splunk + AppDynamics across 200+ microservices), "
                "cutting handoff time 40% with real-time manager dashboards and reducing "
                "weekend on-call escalations by 25%.",
            ],
        }],
        "projects": [],
    }
    master = {"experience": [], "projects": []}
    out, stats = fit_bullets_to_bands(tailored, master)
    final = out["experience"][0]["bullets"][0]
    band = classify(len(final))
    # Either lands in a clean band after safe trim OR is flagged unchanged.
    # Never truncated mid-clause.
    if band not in ("single", "double", "short"):
        assert len(stats["flagged_for_llm"]) >= 1, (
            f"Overlong bullet not flagged after failed safe trim: len={len(final)}"
        )
    # Must still end with proper punctuation — no broken phrase.
    assert final.endswith(".") or final.endswith("constraints") or final.endswith("escalations by 25%"), (
        f"Overlong bullet got truncated mid-sentence: {final!r}"
    )


def test_no_master_match_no_clean_trim_is_flagged():
    """Bullet in forbidden zone with no master variant AND no clean trim
    available should be flagged for LLM rescue, not left silently broken."""
    tailored = {
        "experience": [{
            "company": "Nowhere",
            "role": "Unknown Role",
            "bullets": [
                # 130 chars, no fillers / clauses / parentheticals to trim
                "Designed and deployed a critical pipeline that processes streams of "
                "structured events through validation guardrails daily.",
            ],
        }],
        "projects": [],
    }
    master = {"experience": [], "projects": []}
    out, stats = fit_bullets_to_bands(tailored, master)
    final = out["experience"][0]["bullets"][0]
    if classify(len(final)) == "forbidden":
        assert len(stats["flagged_for_llm"]) >= 1, (
            f"Forbidden bullet not flagged for rescue: "
            f"len={len(final)}, flagged={stats['flagged_for_llm']}"
        )


def test_stats_band_counts_before_and_after(tailored, master):
    _, stats = fit_bullets_to_bands(tailored, master)

    # Before: 7 bullets total, 5 in forbidden, 2 in single
    assert stats["before"]["forbidden"] == 5
    assert stats["before"]["single"] == 2

    # After: forbidden count should be lower (most swapped to master double).
    assert stats["after"]["forbidden"] <= 2, (
        f"After fit, forbidden should be ≤2. Stats: {stats}"
    )


# ---------------------------------------------------------------------------
# Safety regression tests — these guard against the 2026-05-14 bug where
# aggressive trim rules destroyed PAR Result content.
# ---------------------------------------------------------------------------

def test_trim_preserves_trailing_metric_clause():
    """Bullets often end with the PAR Result component (', reducing X by 60%').
    The trim ladder MUST NEVER drop trailing clauses, even when bullet is
    over budget. Regression test for the 2026-05-14 broken-bullet bug."""
    from src.line_fitter import _trim_to_band

    # 145 chars, forbidden zone — ends with the metric clause
    bullet = (
        "Built shift handover platform tracking deliverables and workload across "
        "regional shifts, cutting handoff time by 40% with manager dashboards."
    )
    trimmed = _trim_to_band(bullet, target_max=SINGLE_MAX)
    # The trailing ", cutting handoff time by 40% with manager dashboards."
    # must NOT be dropped. Safe-only trim should either leave the bullet
    # unchanged or remove safe-only fragments (parens / qualifiers).
    assert "40%" in trimmed, (
        f"Trim dropped the 40% metric — that's destroying PAR Result. "
        f"Original ({len(bullet)}): {bullet!r}\n"
        f"Trimmed ({len(trimmed)}): {trimmed!r}"
    )
    assert "manager dashboards" in trimmed, (
        f"Trim dropped the trailing scope clause: {trimmed!r}"
    )


def test_trim_preserves_semicolon_result_clause():
    """A bullet of the form 'X; reduced Y by Z%' must not lose the '; ...'
    Result tail. Specifically prevents the previous Rule 2 regression."""
    from src.line_fitter import _trim_to_band

    bullet = (
        "Engineered config-driven monitoring dashboard with dynamic UI generation "
        "aggregating server health for 30+ teams; reduced MTTD 60%."
    )
    trimmed = _trim_to_band(bullet, target_max=SINGLE_MAX)
    # The semicolon-Result tail must survive — it's THE metric.
    assert "MTTD 60%" in trimmed or "; reduced" in trimmed, (
        f"Trim dropped the semicolon-Result clause: {trimmed!r}"
    )


def test_trim_preserves_oxford_comma_trailing_clause():
    """A bullet ending with ', and X.' (Oxford comma list) must not lose
    the ', and X' portion. Prevents the 'regulatory, cost' regression."""
    from src.line_fitter import _trim_to_band

    bullet = (
        "Partnered with product and ops stakeholders to scope, design, and ship "
        "AI tooling within regulatory, cost, and latency constraints."
    )
    trimmed = _trim_to_band(bullet, target_max=SINGLE_MAX)
    # The Oxford comma tail must survive — it completes the list.
    assert "latency constraints" in trimmed or "and latency" in trimmed, (
        f"Trim dropped Oxford-comma tail: {trimmed!r}"
    )
    # And the bullet must not end mid-list at "cost" or "cost,".
    assert not trimmed.rstrip(".").endswith("cost"), (
        f"Trim left bullet ending mid-list: {trimmed!r}"
    )


def test_forbidden_bullet_with_no_master_match_stays_intact():
    """If a forbidden bullet has no matching master variant AND safe trim
    can't bring it into single-line band, it must be KEPT INTACT (with all
    metrics) — never truncated. May be flagged for LLM rescue."""
    tailored = {
        "experience": [{
            "company": "Nowhere",
            "role": "Unknown",
            "bullets": [
                # 145 chars, forbidden — no parens / qualifiers / verbose
                # phrases for safe trim to remove. Original ends with a
                # metric we must preserve.
                "Designed and built a data ingestion service handling 2M+ events "
                "per day, cutting downstream SLA breaches by 80% within one quarter.",
            ],
        }],
        "projects": [],
    }
    master = {"experience": [], "projects": []}
    out, stats = fit_bullets_to_bands(tailored, master)
    final = out["experience"][0]["bullets"][0]
    # Metric AND completing punctuation must remain.
    assert "80%" in final, f"Lost the 80% metric: {final!r}"
    assert final.rstrip().endswith(".") or "quarter" in final, (
        f"Bullet got truncated mid-sentence: {final!r}"
    )
