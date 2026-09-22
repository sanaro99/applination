"""Content-preserving layout policy for one-page resumes.

Layout operates after editorial and factual decisions.  It accepts ordinary
one-line, one-and-a-half-line, and two-line bullets.  Its only sentence-level
edit is a conservative cleanup when a few characters would create an orphan
wrap; page overflow is otherwise solved by removing the lowest-priority tail
content, whose order was chosen by the editorial writer.
"""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Callable


_SAFE_REWRITES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bin order to\b", re.IGNORECASE), "to"),
    (re.compile(r"\bfor the purpose of\b", re.IGNORECASE), "for"),
    (re.compile(
        r"\b(?:successfully|effectively|generally|various|comprehensively|"
        r"seamlessly|significantly|substantially|primarily|directly|notably)\s+",
        re.IGNORECASE,
    ), ""),
)


def trim_orphan_wrap(text: str, chars_per_line: int, *, orphan_chars: int = 20) -> str:
    """Safely pull a 1-2-word orphan back onto the preceding line.

    If no semantics-preserving cleanup is available, the original complete
    sentence wins over a destructive truncation.
    """
    original = re.sub(r"\s+", " ", (text or "").strip())
    if not original or chars_per_line <= 0:
        return original
    remainder = len(original) % chars_per_line
    if len(original) <= chars_per_line or not 0 < remainder <= orphan_chars:
        return original

    candidates = []
    current = original
    for pattern, replacement in _SAFE_REWRITES:
        candidate = re.sub(r"\s+", " ", pattern.sub(replacement, current)).strip()
        candidate = re.sub(r"\s+([,.;:])", r"\1", candidate)
        if candidate != original and len(candidate) <= chars_per_line * (len(original) // chars_per_line):
            candidates.append(candidate)
        current = candidate
    if not candidates:
        return original
    return max(candidates, key=len)


def repair_orphan_wraps(resume: dict, chars_per_line: int) -> tuple[dict, int]:
    out = deepcopy(resume)
    changed = 0
    for section in ("experience", "projects"):
        for entry in out.get(section) or []:
            bullets = entry.get("bullets") or []
            for index, bullet in enumerate(bullets):
                repaired = trim_orphan_wrap(str(bullet), chars_per_line)
                if repaired != bullet:
                    bullets[index] = repaired
                    changed += 1
    return out, changed


def fit_skill_rows(resume: dict, chars_per_line: int, pinned: list[str] | None = None) -> tuple[dict, list[str]]:
    """Fit each skill category to one approximate line without losing core skills."""
    out = deepcopy(resume)
    protected = {str(value).casefold() for value in pinned or []}
    removed: list[str] = []
    for group in out.get("skills") or []:
        values = group.get("items") or []
        while len(f"{group.get('group', '')}: {', '.join(values)}") > chars_per_line:
            index = next((i for i in range(len(values) - 1, -1, -1)
                          if str(values[i]).casefold() not in protected), None)
            if index is None:
                break
            removed.append(str(values.pop(index)))
    out["skills"] = [group for group in out.get("skills") or [] if group.get("items")]
    return out, removed


def tighten_once(resume: dict) -> tuple[dict, str | None]:
    """Remove one lowest-priority piece of content, preserving section value."""
    out = deepcopy(resume)
    if out.get("activities"):
        out.pop("activities", None)
        return out, "activities"
    if any(entry.get("coursework") for entry in out.get("education") or []):
        for entry in reversed(out.get("education") or []):
            if entry.get("coursework"):
                entry.pop("coursework", None)
                return out, "education.coursework"
    if any(entry.get("honors") for entry in out.get("education") or []):
        for entry in reversed(out.get("education") or []):
            if entry.get("honors"):
                entry.pop("honors", None)
                return out, "education.honors"

    # The writer orders strongest-first. Remove only tail bullets and preserve
    # a useful floor for each selected item.
    candidates: list[tuple[int, str, int]] = []
    for section, floor, section_bias in (("projects", 1, 0), ("experience", 2, 1)):
        for index, entry in enumerate(out.get(section) or []):
            count = len(entry.get("bullets") or [])
            if count > floor:
                candidates.append((count * 10 + section_bias, section, index))
    if candidates:
        _, section, index = max(candidates)
        out[section][index]["bullets"].pop()
        return out, f"{section}.{index}.bullets.tail"

    projects = out.get("projects") or []
    if len(projects) > 2:
        projects.pop()
        return out, "projects.tail"
    return out, None


def shrink_to_budget(
    resume: dict,
    estimate: Callable[[dict], int],
    budget: int,
    *,
    max_steps: int = 24,
) -> tuple[dict, list[str]]:
    out = deepcopy(resume)
    removals: list[str] = []
    for _ in range(max_steps):
        if estimate(out) <= budget:
            break
        tightened, removed = tighten_once(out)
        if removed is None:
            break
        out = tightened
        removals.append(removed)
    return out, removals
