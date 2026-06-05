"""
Deterministic bullet line-fitter.

The printable width of one bullet line depends on the configured body font
size (see configure_for_font). At the project default (10pt Times New Roman,
0.25" L/R margins) a line holds ~132 chars. A bullet that wraps onto a second
line it barely fills leaves visible whitespace that makes a resume look
automated. LLMs notoriously cannot count characters, so we don't ask them to.
Instead, after tailoring this module fits each bullet to one of two clean,
font-derived bands (values shown for 10pt):

    SINGLE-LINE:  ~79 - 125 chars (one packed line)
    DOUBLE-LINE:  ~205 - 258 chars (two packed lines)

Strategy per bullet:
  - Already in either band       -> keep
  - Over DOUBLE_MAX chars        -> trim via priority-ordered regex
  - In the "forbidden zone" (between the bands) ->
        1. Try to swap for a master `bullets_all` variant whose first 6
           words overlap with the tailored bullet (preserves topic).
        2. If no master match, try a SAFE trim (parens / qualifiers /
           verbose phrases). If it lands in single-line band, accept.
        3. Otherwise leave the bullet INTACT and flag for LLM rescue.
           Truncating mid-sentence is strictly worse than wrap-waste.

The caller (tailor_graph.run_tailor_graph) runs this BEFORE the LLM rescue
step, so the LLM is only invoked for genuinely tricky bullets.
"""
from __future__ import annotations
import logging
import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Band constants — font-aware (canonical; tailor_graph reads these at runtime)
# ---------------------------------------------------------------------------
# The printable width of one bullet line depends on the body font size
# (config: output.base_font_size). Measured against real Word/PDF output
# (review 2026-05-24): a hanging-indent bullet at 0.25" L/R margins on US
# Letter holds roughly `1320 / font_pt` characters on one printed line:
#       9pt -> ~147 chars   10pt -> ~132 chars   11pt -> ~120 chars
# The previous hardcoded LINE_CHARS=108 assumed 9pt but still UNDER-counted
# real capacity at every size, so ~180-char bullets — which actually fit one
# full line plus a near-empty sliver at 10pt — were mis-classified as healthy
# two-line bullets (the old [170, 220] "double" band). The bands below are
# derived from the configured font so each bullet is pushed to a *full* single
# line or a *full* double line, never the wrap-waste zone in between.

_CHARS_PER_LINE_AT_1PT = 1320.0   # LINE_CHARS = round(this / font_pt)
DOUBLE_OK_OVERSHOOT = 8           # forgive a touch over DOUBLE_MAX on rewrites

# Set by configure_for_font(); initialized to the project default (10pt) at the
# bottom of this constants block. The pipeline reconfigures from config at run
# start (see main.process_job).
LINE_CHARS: int = 0
SINGLE_MIN: int = 0
SINGLE_TARGET: int = 0
SINGLE_MAX: int = 0
DOUBLE_MIN: int = 0
DOUBLE_MAX: int = 0
FORBIDDEN_LO: int = 0
FORBIDDEN_HI: int = 0
_ACTIVE_FONT_PT: float = 0.0


def configure_for_font(base_size: float) -> None:
    """Recompute the line-fit bands for the given body font size (pt).

    Idempotent. Call once per run with output.base_font_size BEFORE tailoring
    so the deterministic fitter and the LLM rescue both target the real render
    width. classify() and fit_bullets_to_bands() read these module globals at
    call time, so reconfiguring takes effect immediately.
    """
    global LINE_CHARS, SINGLE_MIN, SINGLE_TARGET, SINGLE_MAX, DOUBLE_MIN, DOUBLE_MAX
    global FORBIDDEN_LO, FORBIDDEN_HI, _ACTIVE_FONT_PT
    base_size = float(base_size) or 10.0
    LINE_CHARS = round(_CHARS_PER_LINE_AT_1PT / base_size)
    # LINE_CHARS is already a conservative capacity estimate; measured against
    # real Word/PDF output, average resume text fits ~136 chars on a 10pt line,
    # and 133-char single lines render comfortably inside the margin. So the
    # single ceiling sits just under LINE_CHARS (0.985), not the old 0.95 which
    # was double-conservative and rejected dense single lines the model produces.
    SINGLE_MAX = round(LINE_CHARS * 0.985)              # one full line (130 @ 10pt)
    # Fill FLOOR for a single line: below this the line looks under-packed even
    # though it renders cleanly. Bullets in [SINGLE_MIN, SINGLE_TARGET) are valid
    # singles but get flagged for the rescue to EXTEND toward a full line.
    SINGLE_TARGET = round(LINE_CHARS * 0.88)            # ~88% fill (116 @ 10pt)
    SINGLE_MIN = round(LINE_CHARS * 0.60)               # below this looks half-empty
    DOUBLE_MIN = LINE_CHARS + round(LINE_CHARS * 0.55)  # 2nd line >= ~55% full
    DOUBLE_MAX = LINE_CHARS * 2 - 6                     # two full lines (small safety)
    FORBIDDEN_LO = SINGLE_MAX + 1
    FORBIDDEN_HI = DOUBLE_MIN - 1
    _ACTIVE_FONT_PT = base_size


configure_for_font(10.0)   # project default; pipeline overrides from config


def classify(length: int) -> str:
    """Return one of: 'single' | 'double' | 'forbidden' | 'short' | 'overlong'."""
    if length < SINGLE_MIN:
        return "short"
    if length <= SINGLE_MAX:
        return "single"
    if FORBIDDEN_LO <= length <= FORBIDDEN_HI:
        return "forbidden"
    if DOUBLE_MIN <= length <= DOUBLE_MAX:
        return "double"
    if length < FORBIDDEN_LO:
        # 106-113: technically wraps but only by a few chars; treat as forbidden
        return "forbidden"
    return "overlong"   # > DOUBLE_MAX


def is_underfilled_single(length: int) -> bool:
    """A bullet that renders as a clean single line but leaves the line under
    ~88% full — a soft quality signal (NOT a render failure). The rescue tries
    to extend these toward a full line using real master-pool detail."""
    return SINGLE_MIN <= length < SINGLE_TARGET


def is_clean(length: int) -> bool:
    return classify(length) in ("single", "double")


# ---------------------------------------------------------------------------
# Trim ladder — applied in order until the bullet lands in target band
# ---------------------------------------------------------------------------

# Each rule is (regex, replacement). SAFE transformations ONLY — we never
# drop trailing clauses because resume bullets put the PAR Result (metric,
# outcome) at the end. Cutting trailing content destroys signal AND can
# produce mid-sentence bullets that look unprofessional.
#
# What used to be here (DELETED 2026-05-14):
#   - "drop trailing '; clause'"  — often the metric.
#   - "drop trailing ', and X'"   — often a completing item / metric.
#   - "drop trailing ', X'"       — almost always the result.
# These caused the broken "regulatory, cost" and missing-metric bugs.
_TRIM_RULES: list[tuple[re.Pattern[str], str]] = [
    # 1. Drop parentheticals — usually non-load-bearing context like
    # "(~50K docs)" or "(Aug 2022)". Dates may carry signal; we accept the
    # tradeoff since parentheticals are rarely the PAR Result component.
    (re.compile(r"\s*\([^()]*\)"), ""),
    # 2. Drop qualifier/filler adverbs and adjectives (safe — these add
    # nothing to recruiter scan).
    (re.compile(
        r"\b("
        r"essentially|effectively|generally|various|comprehensively?|"
        r"robustly?|seamlessly?|innovatively?|successfully|significantly|"
        r"substantially|primarily|directly|notably"
        r")\s*",
        re.IGNORECASE,
    ), ""),
    # 3. "in order to" -> "to"
    (re.compile(r"\bin order to\b", re.IGNORECASE), "to"),
    # 4. "for the purpose of" -> "for"
    (re.compile(r"\bfor the purpose of\b", re.IGNORECASE), "for"),
    # 5. Doubled spaces collapse (cleanup after the rules above).
    (re.compile(r"  +"), " "),
]


def _trim_to_band(
    text: str,
    target_max: int | None = None,
    *,
    hard_floor: int = 50,
) -> str:
    """Apply trim rules incrementally until length <= target_max.

    Goal: land at or under target_max while preserving PAR content. We
    accept any result down to `hard_floor` (default 50 chars) — anything
    shorter loses too much signal. The trim ladder stops on the first
    rule that lands the result in (hard_floor, target_max].
    """
    if target_max is None:
        target_max = SINGLE_MAX
    result = text.strip()
    if len(result) <= target_max:
        return result

    last_good = result
    for pattern, replacement in _TRIM_RULES:
        candidate = pattern.sub(replacement, result).strip()
        candidate = re.sub(r"\s+([,.;])", r"\1", candidate)
        candidate = re.sub(r"\s+", " ", candidate).strip()
        if candidate == result:
            continue   # this rule didn't match
        # If a single rule cut us below the hard floor while previous state
        # was still over budget, prefer the previous (longer) state.
        if len(candidate) < hard_floor and len(result) > target_max:
            return last_good if last_good != text else result
        result = candidate
        if len(result) <= target_max:
            last_good = result
            return result
        last_good = result

    return last_good


# ---------------------------------------------------------------------------
# Master variant lookup
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def _first_n_words(text: str, n: int = 6) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text)[:n]]


def _word_overlap(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    a_set, b_set = set(a), set(b)
    return len(a_set & b_set) / max(len(a_set), len(b_set))


def _normalize_role_head(role: str) -> str:
    """Strip parenthetical role qualifiers so 'Sr. SWE (Authorized Officer)'
    matches the master entry's 'Sr. Software Engineer (Authorized Officer)'."""
    return (role or "").lower().split("(")[0].strip()


def _master_pool_for(master: dict, section: str, item: dict) -> list[str]:
    """Return master `bullets_all` pool for the section item, or []."""
    if section == "experience":
        role = _normalize_role_head(item.get("role", ""))
        company = (item.get("company", "") or "").lower()
        for e in master.get("experience", []) or []:
            mrole = _normalize_role_head(e.get("role", ""))
            mco = (e.get("company", "") or "").lower()
            if mco == company and (mrole in role or role.startswith(mrole[:18])):
                return list(e.get("bullets_all") or e.get("bullets") or [])
        return []

    if section == "projects":
        name = (item.get("name", "") or "").lower()
        for p in master.get("projects", []) or []:
            mname = (p.get("name", "") or "").lower()
            if mname == name or name in mname or mname in name:
                return list(p.get("bullets_all") or p.get("bullets") or [])
    return []


def _find_double_variant(
    current_bullet: str,
    master_pool: list[str],
    already_used: set[str],
) -> str | None:
    """Find a master variant that (a) sits in the double-line band, and
    (b) shares enough of its first words with the current bullet so we
    don't swap the topic. Return None if nothing qualifies."""
    if not master_pool:
        return None
    current_first = _first_n_words(current_bullet, 6)

    candidates: list[tuple[float, str]] = []
    for variant in master_pool:
        v = variant.strip()
        if not v or v in already_used:
            continue
        if classify(len(v)) != "double":
            continue
        overlap = _word_overlap(current_first, _first_n_words(v, 6))
        if overlap >= 0.5:
            candidates.append((overlap, v))

    if not candidates:
        return None
    # Highest overlap wins; tie-break by length closest to the middle of the
    # double band (font-aware).
    band_mid = (DOUBLE_MIN + DOUBLE_MAX) // 2
    candidates.sort(key=lambda x: (-x[0], abs(len(x[1]) - band_mid)))
    return candidates[0][1]


# ---------------------------------------------------------------------------
# Main API
# ---------------------------------------------------------------------------

@dataclass
class _Offender:
    section: str
    item_idx: int
    bullet_idx: int
    original: str
    label: str = ""        # "role @ company" or project name
    master_pool: list[str] = field(default_factory=list)


def _band_counts(tailored: dict) -> dict[str, int]:
    """Count bullets in each band across experience + projects."""
    counts = {"single": 0, "double": 0, "forbidden": 0, "short": 0, "overlong": 0}
    for section in ("experience", "projects"):
        for entry in tailored.get(section, []) or []:
            for b in entry.get("bullets") or []:
                if isinstance(b, str):
                    counts[classify(len(b))] = counts.get(classify(len(b)), 0) + 1
    return counts


def fit_bullets_to_bands(tailored: dict, master: dict) -> tuple[dict, dict]:
    """Fit every bullet to the single-line or double-line band.

    Returns (updated_tailored, stats). Mutates a deepcopy, not the input.

    stats keys:
      - before: band counts
      - after: band counts
      - expanded: how many bullets were swapped for a longer master variant
      - trimmed: how many bullets were shortened by regex rules
      - flagged_for_llm: list of {section, item_idx, bullet_idx, text, length}
        — bullets the deterministic fitter couldn't resolve. The caller
        should pass these to an LLM rescue pass.
    """
    out = deepcopy(tailored)
    stats: dict[str, Any] = {
        "before": _band_counts(out),
        "expanded": 0,
        "trimmed": 0,
        "flagged_for_llm": [],
    }

    # Track which master variants we've already used in this resume so we
    # don't substitute the same line twice for two different bullets.
    used_master: set[str] = set()

    for section in ("experience", "projects"):
        for item_idx, entry in enumerate(out.get(section, []) or []):
            bullets = entry.get("bullets") or []
            master_pool = _master_pool_for(master, section, entry)

            for j, bullet in enumerate(bullets):
                if not isinstance(bullet, str):
                    continue
                band = classify(len(bullet))

                if band in ("single", "double", "short"):
                    # Renders cleanly. But a single line under ~88% full wastes
                    # horizontal space — if we have real master detail to draw
                    # on, flag it for the rescue to EXTEND toward a full line.
                    # (No master pool -> leave it; padding from nothing risks
                    # fabrication.) `short`/`double` are left as-is.
                    if (band == "single" and is_underfilled_single(len(bullet))
                            and master_pool):
                        stats["flagged_for_llm"].append({
                            "section": section, "item_idx": item_idx,
                            "bullet_idx": j, "text": bullet,
                            "length": len(bullet), "mode": "extend",
                        })
                    continue

                if band == "overlong":
                    # Slight overshoot (DOUBLE_MAX+1 .. DOUBLE_MAX+8): keep
                    # as-is. Bullets in this range wrap to 2 lines and fill
                    # them — recruiter doesn't see a half-empty wrap.
                    if len(bullet) <= DOUBLE_MAX + DOUBLE_OK_OVERSHOOT:
                        continue
                    # Significantly over (>228). Apply only SAFE trims
                    # (parens, qualifiers, verbose phrases) and accept any
                    # outcome that lands in single OR double band. If safe
                    # trims aren't enough, leave the bullet alone and flag
                    # for LLM rescue — better than truncating PAR content.
                    trimmed = _trim_to_band(bullet, target_max=DOUBLE_MAX)
                    if (DOUBLE_MIN <= len(trimmed) <= DOUBLE_MAX + DOUBLE_OK_OVERSHOOT
                            or len(trimmed) <= SINGLE_MAX):
                        if trimmed != bullet:
                            bullets[j] = trimmed
                            stats["trimmed"] += 1
                            continue
                    # Safe trim couldn't fix it. Flag for LLM rescue rather
                    # than fall back to unsafe trailing-clause cuts.
                    stats["flagged_for_llm"].append({
                        "section": section, "item_idx": item_idx, "bullet_idx": j,
                        "text": bullet, "length": len(bullet), "mode": "compress",
                    })
                    continue

                # band == "forbidden" (114-169):
                # Step A: try expand-from-master. With the widened band most
                # `bullets_all` variants now qualify as `double`, so this
                # is the primary recovery path.
                substitute = _find_double_variant(bullet, master_pool, used_master)
                if substitute:
                    bullets[j] = substitute
                    used_master.add(substitute)
                    stats["expanded"] += 1
                    continue

                # Step B: try SAFE-only trim (no trailing-clause cuts). If a
                # bullet has a parenthetical or filler we can drop, this may
                # bring it into single-line band cleanly.
                trimmed = _trim_to_band(bullet, target_max=SINGLE_MAX)
                if len(trimmed) <= SINGLE_MAX and trimmed != bullet:
                    bullets[j] = trimmed
                    stats["trimmed"] += 1
                    continue

                # Step C: NO truncation. A forbidden but COMPLETE bullet
                # (wrap-waste but with a metric) beats a single-line bullet
                # with the PAR Result chopped off. Leave the bullet alone
                # and flag for the LLM rescue layer to creatively rewrite.
                stats["flagged_for_llm"].append({
                    "section": section, "item_idx": item_idx, "bullet_idx": j,
                    "text": bullet, "length": len(bullet), "mode": "compress",
                })

    stats["after"] = _band_counts(out)
    LOG.info(
        "line_fitter: %s -> %s (expanded=%d, trimmed=%d, flagged_for_llm=%d)",
        stats["before"], stats["after"],
        stats["expanded"], stats["trimmed"], len(stats["flagged_for_llm"]),
    )
    return out, stats
