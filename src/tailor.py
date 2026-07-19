"""
LLM-backed ranking and tailoring.

Responsibilities:
  1. rank_jobs(jobs, user_profile) -> scores each job 0-100 for fit
  2. tailor_resume(master_resume, job) -> structured JSON for one-page render
  3. write_cover_letter(source, job, user, bio, stories, example_letter) -> plain text

Uses the LLMProvider abstraction from src/providers/ — no direct API imports here.
"""
from __future__ import annotations
import json
import logging
import re
from typing import Any

from .providers import LLMProvider
from .providers.factory import is_quota_error, try_chain
from .reference_loader import (
    BIO_CAP,
    COVER_LETTER_BIO_CAP,
    STORY_BODY_CAP,
    STORY_CANDIDATE_CAP,
)

LOG = logging.getLogger(__name__)


def _strip_em_dashes(text: str) -> str:
    """Replace em dashes (U+2014) with a comma, handling surrounding whitespace.

    We never want em dashes in any output — they break some ATS parsers and
    the user has explicitly asked for zero em dashes in resumes and letters.
    En dashes (U+2013) used for date ranges (Mar 2024 – Aug 2025) are kept.
    """
    return re.sub(r"\s*—\s*", ", ", text)

# Soft caps for the LLM. The page-fit pass in resume_builder.py is the
# real one-page enforcer — it both shrinks overflow AND expands undersized
# content from the master so the page doesn't look half empty.
#
# These limits are intentionally generous so the LLM produces enough raw
# material to fill the page; the renderer trims back if it overflows.
RESUME_CONSTRAINTS = {
    "summary_max_chars": 320,
    "skills_max_total": 42,          # across all groups
    "skills_groups_max": 6,
    # _ensure_core_experience guarantees every full-time role plus the most
    # recent entry overall; 3 leaves headroom beyond a typical 2 full-time
    # roles so a current internship isn't crowded out by older history.
    "experience_max_items": 3,
    "experience_bullets_per_item": 5,
    # Single-line max. NOTE: the authoritative, font-aware bullet bands live in
    # src/line_fitter.py::configure_for_font (10pt single target 116-125). These
    # values are kept aligned to that single max to avoid contradicting the
    # prompt guidance, which interpolates the live line_fitter bands.
    "experience_bullet_max_chars": 125,
    "projects_max_items": 3,
    "projects_bullets_per_item": 2,
    "projects_bullet_max_chars": 125,     # single-line max (see note above)
    "education_max_items": 2,
}

# Canonical skill group names. The LLM is told to use EXACTLY these strings.
# Keeping the set small + standardized stops the snake_case leakage we
# previously saw (`ai_ml`, `web_and_apis`) showing up in rendered output.
CANONICAL_SKILL_GROUPS = [
    "Languages",
    "AI / ML",
    "Frameworks & APIs",
    "Cloud & DevOps",
    "Data & Storage",
    "Infrastructure & SRE",
    "Engineering Practices",
]


# ---------------------------------------------------------------------
# Post-processing helpers — guarantees enforced in code, not prompt
# ---------------------------------------------------------------------

# Map LLM-invented group names to canonical ones so merging and dedup work.
_CANONICAL_GROUP_ALIASES: dict[str, str] = {
    "ai_ml": "AI / ML",
    "ai/ml": "AI / ML",
    "artificial intelligence": "AI / ML",
    "machine learning": "AI / ML",
    "ml": "AI / ML",
    "cloud": "Cloud & DevOps",
    "cloud and devops": "Cloud & DevOps",
    "cloud & devops": "Cloud & DevOps",
    "devops_cloud": "Cloud & DevOps",
    "devops and cloud": "Cloud & DevOps",
    "devops": "Cloud & DevOps",
    "data": "Data & Storage",
    "databases": "Data & Storage",
    "database": "Data & Storage",
    "frameworks": "Frameworks & APIs",
    "frameworks and apis": "Frameworks & APIs",
    "frameworks & libraries": "Frameworks & APIs",
    "web_and_apis": "Frameworks & APIs",
    "web and apis": "Frameworks & APIs",
    "apis": "Frameworks & APIs",
    "tools": "Engineering Practices",
    "infrastructure": "Infrastructure & SRE",
    "sre": "Infrastructure & SRE",
    "sre_infra": "Infrastructure & SRE",
    "sre and infra": "Infrastructure & SRE",
    "languages": "Languages",
    "programming languages": "Languages",
    "engineering": "Engineering Practices",
    "engineering practices": "Engineering Practices",
    "engineering practice": "Engineering Practices",
    "practices": "Engineering Practices",
    "other": "Engineering Practices",
}


def _normalize_dates_field(entry: dict) -> dict:
    """Reconstruct ``dates`` from start_date/end_date with a clean en-dash.

    LLMs often emit malformed dates (em-dash that gets stripped, double spaces,
    missing dash entirely). When the entry has start_date/end_date, prefer
    those for a deterministic ``Mar 2024 – Aug 2025`` format. Mutates and
    returns the entry.
    """
    if not isinstance(entry, dict):
        return entry
    start = (entry.get("start_date") or "").strip()
    end = (entry.get("end_date") or "").strip()
    if start or end:
        end_norm = end if end else "Present"
        entry["dates"] = f"{start} – {end_norm}".strip(" –")
        return entry
    # No structured fields — try to repair the dates string itself
    cur = (entry.get("dates") or "").strip()
    if cur and "–" not in cur and "—" not in cur and "-" not in cur:
        # "Mar 2024  Aug 2025" → "Mar 2024 – Aug 2025"
        entry["dates"] = re.sub(r"\s{2,}", " – ", cur)
    elif "  " in cur:
        # "Mar 2024  Aug 2025" leftover from earlier em-dash strip
        entry["dates"] = re.sub(r"\s{2,}", " – ", cur)
    return entry


# Maximum items rendered per skill group. Keeps the resume from listing
# 19 Apache-* tools that visually overwhelm a recruiter and harm ATS
# keyword density (relevant terms get diluted by tail entries).
SKILLS_ITEMS_PER_GROUP_MAX = 11


def _normalize_resume_json(result: dict) -> dict:
    """Fix common LLM output artifacts before post-processing.

    Handles three classes of corruption the OpenRouter free-tier model produces:
    1. String values that start with ': ' (YAML-style colon artifact)
    2. Skills stored under a garbage key (e.g. ': [{') instead of 'skills'
    3. Non-canonical skill group names and duplicate items within/across groups
    Plus applies date-format normalization and a per-group skill cap.
    """
    if not isinstance(result, dict):
        return result

    # 1. Strip leading ': ' from all top-level string values.
    cleaned: dict = {}
    for k, v in result.items():
        cleaned[k] = v[2:] if isinstance(v, str) and v.startswith(": ") else v
    result = cleaned

    # 2. Recover skills when stored under a garbage key.
    if not isinstance(result.get("skills"), list):
        for k, v in list(result.items()):
            if k == "skills":
                continue
            if isinstance(v, list) and v and isinstance(v[0], dict):
                if "group" in v[0] or "items" in v[0]:
                    result["skills"] = v
                    break

    # 3. Normalize group names, merge duplicates, deduplicate items globally.
    skills = result.get("skills")
    if isinstance(skills, list):
        # Rename non-canonical group names.
        for g in skills:
            if isinstance(g, dict) and "group" in g:
                alias = _CANONICAL_GROUP_ALIASES.get(g["group"].strip().lower())
                if alias:
                    g["group"] = alias

        # Merge groups that share the same (now-canonical) name.
        merged: dict[str, list] = {}
        order: list[str] = []
        for g in skills:
            if isinstance(g, dict):
                name = g.get("group", "Other")
                if name not in merged:
                    merged[name] = []
                    order.append(name)
                merged[name].extend(g.get("items") or [])

        # Deduplicate globally — first occurrence wins (case-insensitive).
        seen: set[str] = set()
        deduped = []
        for name in order:
            items: list[str] = []
            for it in merged[name]:
                s = str(it).strip()
                if s and s.lower() not in seen:
                    seen.add(s.lower())
                    items.append(s)
            deduped.append({"group": name, "items": items})

        # Absorb singleton/empty groups into Engineering Practices so they don't
        # render as half-empty lines. Groups with ≤ 2 items look bad in the resume.
        final: list[dict] = []
        overflow: list[str] = []
        for g in deduped:
            if len(g["items"]) <= 2:
                overflow.extend(g["items"])
            else:
                final.append(g)
        if overflow:
            ep = next((g for g in final if g["group"] == "Engineering Practices"), None)
            if ep:
                existing = {i.lower() for i in ep["items"]}
                ep["items"].extend(i for i in overflow if i.lower() not in existing)
            else:
                final.append({"group": "Engineering Practices", "items": overflow})

        # Cap per-group items so a bloated "Data & Storage" with 19 entries
        # doesn't drown out the relevant ones. Trailing items are dropped.
        for g in final:
            if len(g["items"]) > SKILLS_ITEMS_PER_GROUP_MAX:
                g["items"] = g["items"][:SKILLS_ITEMS_PER_GROUP_MAX]

        result["skills"] = final

    # Normalize dates on every experience entry so the renderer always gets
    # ``Mar 2024 – Aug 2025`` rather than the LLM's malformed variants.
    for entry in result.get("experience", []) or []:
        _normalize_dates_field(entry)

    return result


def _ensure_core_experience(tailored: dict, master: dict, profile: dict | None = None) -> dict:
    """Guarantee the candidate's full-time roles AND their current/most-recent
    role are present in the output.

    The LLM occasionally drops a full-time role when the JD doesn't strongly
    map to that work — or drops the most recent role in favor of older, more
    keyword-dense ones (e.g. a current internship losing out to a past
    full-time job). We splice the missing role(s) back from the master so the
    candidate's primary professional history, and what they're doing right
    now, is never hidden. "Full-time" is simply any experience entry whose
    title is not an internship — derived from the resume, not tied to any
    specific employer. Skipped when the profile opts out via
    ``preserve_fulltime: false``.
    """
    if profile is not None and not profile.get("preserve_fulltime", True):
        return tailored

    master_exp = master.get("experience", []) or []
    if not master_exp:
        return tailored

    # Identify the full-time roles in the master (anything that isn't an
    # internship). They are listed most-recent first by convention.
    def _is_fulltime(e: dict) -> bool:
        role = (e.get("role") or "").strip().lower()
        return "intern" not in role

    required = [e for e in master_exp if _is_fulltime(e)]
    # Master entries are most-recent-first by convention — always guarantee
    # that first entry too (even if it's an internship), so a current
    # internship can't be crowded out by older full-time history.
    most_recent = master_exp[0]
    if most_recent not in required:
        required = [most_recent] + required
    if not required:
        return tailored

    out = list(tailored.get("experience", []) or [])

    def _matches(req: dict, candidate: dict) -> bool:
        rc = (req.get("company") or "").strip().lower()
        cc = (candidate.get("company") or "").strip().lower()
        if rc != cc:
            return False
        # Two roles at the same company share most of the role string ("software
        # engineer" is a substring of "sr. software engineer"). Disambiguate using
        # the start date — anchored to the START of cand_dates so that
        # "Mar 2024" in "Jul 2021 – Mar 2024" doesn't false-match.
        req_start = (req.get("start_date") or "").strip().lower()
        cand_dates = (candidate.get("dates") or "").strip().lower()
        if req_start and cand_dates.startswith(req_start):
            return True
        # Fallback: look for the senior/junior marker explicitly so a senior
        # role doesn't satisfy a junior requirement (or vice versa).
        rr = (req.get("role") or "").strip().lower()
        cr = (candidate.get("role") or "").strip().lower()
        req_is_senior = rr.startswith("sr") or rr.startswith("senior")
        cand_is_senior = cr.startswith("sr") or cr.startswith("senior")
        return req_is_senior == cand_is_senior

    for req in required:
        canonical_dates = f"{req.get('start_date','')} – {req.get('end_date','')}".strip(" –")
        matched = [e for e in out if _matches(req, e)]
        if matched:
            # The role exists, but the LLM may have rewritten the title/company
            # (e.g. invented "(Authorized Officer)" or dropped a real suffix).
            # Pin the identity fields back to the master; keep the tailored bullets.
            for e in matched:
                e["company"] = req.get("company", "")
                e["role"] = req.get("role", "")
                e["location"] = req.get("location", "")
                e["dates"] = canonical_dates
        else:
            out.append({
                "company": req.get("company", ""),
                "role": req.get("role", ""),
                "location": req.get("location", ""),
                "dates": canonical_dates,
                "bullets": (req.get("bullets_all") or [])[:4],
            })

    # Sort experience to follow master order (most-recent-first by convention).
    # A role matched to the master gets the master's index; unknown roles stay
    # at the end in their original relative order.
    master_index: dict[tuple[str, str], int] = {}
    for idx, m in enumerate(master_exp):
        co = (m.get("company") or "").strip().lower()
        start = (m.get("start_date") or "").strip().lower()
        master_index[(co, start)] = idx

    def _sort_key(e: dict) -> tuple[int, int]:
        co = (e.get("company") or "").strip().lower()
        dates = (e.get("dates") or "").strip().lower()
        # Find a master entry whose start_date prefixes this entry's dates.
        for (m_co, m_start), m_idx in master_index.items():
            if co == m_co and m_start and dates.startswith(m_start):
                return (0, m_idx)
        return (1, 0)  # unknown roles after known ones, original order via stable sort

    out.sort(key=_sort_key)
    # Cap at the configured item budget, but never below the count of
    # guaranteed full-time roles (a smaller budget must not cut a required
    # role that was just spliced back in above).
    cap = max(len(required), RESUME_CONSTRAINTS["experience_max_items"])
    tailored["experience"] = out[:cap]
    return tailored


# Generic role nouns that signal the summary's opening identity was lifted from
# the JD rather than the candidate's real title. The candidate's OWN identity
# tokens are subtracted from this set at runtime (a data scientist legitimately
# leads with "scientist"), and the early-career words are only forbidden for
# someone whose profile seniority is "professional".
_BASE_FORBIDDEN_IDENTITY_NOUNS = {
    "marketing", "manager", "management", "designer", "analyst", "scientist",
    "consultant", "specialist", "architect", "advocate", "strategist",
    "associate", "recruiter", "founder", "hacker", "evangelist",
    # Common role nouns: only forbidden when they are NOT the candidate's own
    # title token (e.g. "engineer" stays allowed for a software engineer but is
    # forbidden for a data scientist whose summary parrots a "... Engineer" JD).
    "engineer", "developer", "programmer",
}
_EARLY_CAREER_NOUNS = {"intern", "new grad", "new-grad", "student"}


def _build_forbidden_identity_regex(profile: dict) -> re.Pattern:
    """Role nouns that are NOT this candidate's real identity. Built per-profile
    so a candidate's own title words (e.g. 'scientist' for a data scientist) are
    never treated as fabrications."""
    own = profile.get("identity_tokens") or set()
    nouns = set(_BASE_FORBIDDEN_IDENTITY_NOUNS) - {w.lower() for w in own}
    if profile.get("seniority", "professional") == "professional":
        nouns |= _EARLY_CAREER_NOUNS
    parts = [re.escape(n).replace(r"\ ", r"\s+") for n in sorted(nouns)]
    return re.compile(r"\b(" + "|".join(parts) + r")\b", re.IGNORECASE)


def _normalize_summary_identity(summary: str, profile: dict) -> str:
    """Ensure the summary's opening identity is one of the candidate's REAL
    titles, not the JD's job title. Conservative: only acts when the opening
    clause (before the first ' with ') names a role noun that is NOT the
    candidate's and the clause does not already contain a real title. Any
    JD-relevant focus adjective the LLM legitimately attached to a real title is
    preserved (because the title-present check short-circuits first)."""
    titles = profile.get("identity_titles") or []
    if not titles:
        return summary
    m = re.match(r"^(.{0,80}?)\bwith\b", summary, re.IGNORECASE)
    if not m:
        return summary
    lead = m.group(1)
    low = lead.lower()
    # Already leads with a real title (possibly with a focus adjective) — leave it.
    if any(t.lower() in low for t in titles):
        return summary
    forbidden = _build_forbidden_identity_regex(profile)
    if not forbidden.search(lead):
        return summary
    # Replace the parroted identity with the candidate's primary real title.
    return f"{profile['primary_title']} " + summary[m.end(1):]


def _scrub_summary_fabrications(tailored: dict, profile: dict | None = None) -> dict:
    """Deterministic last line of defense against a fabricated opening identity.

    The summary prompt already instructs the LLM to lead with the candidate's
    real title, but smaller / free-tier models occasionally parrot the JD's job
    title instead. This rewrites the opening identity back to a real title using
    the per-candidate profile. Logs every rewrite for auditability.
    """
    summary = tailored.get("summary")
    if not isinstance(summary, str) or not summary or not profile:
        return tailored
    new_summary = _normalize_summary_identity(summary, profile)
    if new_summary != summary:
        LOG.warning("Normalized summary identity -> %r", new_summary[:60])
        tailored["summary"] = new_summary
    return tailored


def _dedupe_projects_vs_experience(tailored: dict) -> dict:
    """Drop projects already covered by an experience bullet.

    A flagship project sometimes appears both as an experience bullet AND as a
    stand-alone project, wasting a quarter of the page on a duplicate. Match by
    project name substring against the bullet text (case-insensitive). If
    filtering would leave zero projects, keep the duplicate so the resume isn't
    empty there.
    """
    projects = tailored.get("projects")
    experience = tailored.get("experience")
    if not isinstance(projects, list) or not projects:
        return tailored
    if not isinstance(experience, list):
        return tailored

    bullet_blob = " ".join(
        str(b).lower()
        for exp in experience if isinstance(exp, dict)
        for b in (exp.get("bullets") or [])
    )
    if not bullet_blob:
        return tailored

    kept: list[dict] = []
    dropped: list[str] = []
    for p in projects:
        if not isinstance(p, dict):
            kept.append(p)
            continue
        name = (p.get("name") or "").strip().lower()
        if name and name in bullet_blob:
            dropped.append(p.get("name", ""))
            continue
        kept.append(p)

    if not kept and projects:
        # Refuse to leave the Projects section empty; keep all originals.
        return tailored

    if dropped:
        LOG.info("Dropped %d duplicate projects (already in experience): %s",
                 len(dropped), dropped)
    tailored["projects"] = kept
    return tailored


def _ensure_core_skills(tailored: dict, master: dict) -> dict:
    """Guarantee that every entry in master['core_skills'] appears somewhere
    in the tailored skills list. Adds them to the most-appropriate group
    (Languages / Engineering Practices / Cloud & DevOps) if missing."""
    core = master.get("core_skills") or []
    if not core:
        return tailored

    skills = tailored.get("skills")
    # Coerce dict-shape into list (mirrors _normalize_skills logic so the
    # post-processor doesn't rely on rendering order).
    if isinstance(skills, dict):
        skills = [{"group": k, "items": list(v) if isinstance(v, list) else []}
                  for k, v in skills.items()]
    if not isinstance(skills, list):
        skills = []

    # Build a flat lowercase set of what's already present.
    present = set()
    for g in skills:
        if isinstance(g, dict):
            for it in g.get("items") or []:
                present.add(str(it).strip().lower())

    # Bucket missing core skills by best-fit group name.
    def _bucket(skill: str) -> str:
        s = skill.lower()
        if s in {"python", "java", "c++", "javascript", "typescript", "sql", "shell", "go"}:
            return "Languages"
        if s in {"docker", "ci/cd", "kubernetes", "aws", "gcp", "azure", "terraform"}:
            return "Cloud & DevOps"
        if s in {"rest apis", "graphql", "grpc"}:
            return "Frameworks & APIs"
        # "git" and other version-control / generic dev tools land here so
        # they never spawn a singleton "Tools" group (recruiter eyesore).
        return "Engineering Practices"

    by_group: dict[str, list[str]] = {}
    for sk in core:
        if sk.strip().lower() not in present:
            by_group.setdefault(_bucket(sk), []).append(sk)

    if not by_group:
        tailored["skills"] = skills
        return tailored

    # Inject into existing groups when present, else append a new group.
    existing_names = {g.get("group", "").strip().lower(): g for g in skills if isinstance(g, dict)}
    for group_name, items in by_group.items():
        key = group_name.lower()
        if key in existing_names:
            existing_names[key]["items"] = list(existing_names[key].get("items") or []) + items
        else:
            skills.append({"group": group_name, "items": items})
            existing_names[group_name.lower()] = skills[-1]

    # Pad to a minimum count from the master's full skills pool so the skills
    # section is never embarrassingly sparse (4-5 items is not enough ATS coverage).
    SKILLS_MINIMUM = 25
    total = sum(len(g.get("items") or []) for g in skills if isinstance(g, dict))
    if total < SKILLS_MINIMUM:
        master_skills_raw = master.get("skills") or {}
        if isinstance(master_skills_raw, dict):
            pool = list(master_skills_raw.items())
        elif isinstance(master_skills_raw, list):
            pool = [(g.get("group", "Skills"), g.get("items", [])) for g in master_skills_raw
                    if isinstance(g, dict)]
        else:
            pool = []

        existing_names = {g.get("group", "").strip().lower(): g for g in skills if isinstance(g, dict)}
        for raw_name, raw_items in pool:
            if total >= SKILLS_MINIMUM:
                break
            if not isinstance(raw_items, list):
                continue
            key = str(raw_name).strip().lower()
            group_obj = existing_names.get(key)
            if group_obj is None:
                group_obj = {"group": str(raw_name).strip(), "items": []}
                skills.append(group_obj)
                existing_names[key] = group_obj
            for it in raw_items:
                it_s = str(it).strip()
                if not it_s or it_s.lower() in present:
                    continue
                group_obj.setdefault("items", []).append(it_s)
                present.add(it_s.lower())
                total += 1
                if total >= SKILLS_MINIMUM:
                    break

    # Defensive: if core-skill injection landed a singleton (e.g., the
    # tailored output dropped "Engineering Practices" entirely and we just
    # re-added it with only "Git"), absorb singletons back into the largest
    # group so the resume never renders a one-item skill row.
    singletons: list[str] = []
    kept: list[dict] = []
    for g in skills:
        if isinstance(g, dict) and len(g.get("items") or []) <= 1:
            singletons.extend(g.get("items") or [])
        else:
            kept.append(g)
    if singletons and kept:
        # Prefer Engineering Practices as the absorption target; else largest.
        target = next((g for g in kept if g.get("group") == "Engineering Practices"), None)
        if target is None:
            target = max(kept, key=lambda g: len(g.get("items") or []))
        existing = {str(i).strip().lower() for i in target.get("items") or []}
        for it in singletons:
            if it.strip().lower() not in existing:
                target.setdefault("items", []).append(it)
                existing.add(it.strip().lower())
        skills = kept

    tailored["skills"] = skills
    return tailored


# Phrases that only appear in our prompt template, never in a real letter.
# Covers both the current prompt and the previous format so old model responses
# are also detected. If the model echoes any of these back, it failed to follow
# the output constraint.
_PROMPT_LEAKAGE_MARKERS = [
    # Current prompt — system
    "Your response is the cover letter body and nothing else",
    "How to write each paragraph",
    "Opening paragraph (2-4 sentences)",
    "Story paragraph (4-7 sentences)",
    "Closing paragraph (2-3 sentences)",
    # Current prompt — user
    "Story material:",
    "Candidate voice",
    "Job description:",
    "Write the letter. Start directly",
    # Previous prompt format (kept so old cached model responses are still caught)
    "=== STRUCTURE (follow exactly) ===",
    "=== ABSOLUTE RULES ===",
    "Paragraph 1 — HOOK",
    "Paragraph 2 — STORY",
    "Paragraph 3 — CONNECTOR",
    "HOOK (2-4 sentences)",
    "STORY MATERIAL:",
    "VOICE CALIBRATION",
    "FULL JD:",
    "Write the three-paragraph letter body now",
]


def _strip_prompt_leakage(raw: str) -> str | None:
    """Detect and recover from models that echo the prompt in their response.

    Returns the extracted letter text if leakage is found, or None if the
    response looks clean. Returns empty string if leakage is found but no
    recoverable letter content exists after the marker blocks.
    """
    upper = raw.upper()
    if not any(m.upper() in upper for m in _PROMPT_LEAKAGE_MARKERS):
        return None  # Clean — no leakage

    LOG.warning(
        "Prompt leakage detected in cover letter (%d chars). Attempting recovery.", len(raw)
    )

    # Find the furthest position where a prompt marker ends.
    # The actual letter should start after the last instruction block.
    last_marker_end = 0
    for marker in _PROMPT_LEAKAGE_MARKERS:
        idx = raw.upper().find(marker.upper())
        if idx >= 0:
            end = idx + len(marker)
            newline = raw.find("\n", end)
            last_marker_end = max(last_marker_end, newline + 1 if newline >= 0 else end)

    candidate = raw[last_marker_end:].strip()

    # A valid 3-paragraph letter is at least 150 chars with at least one paragraph break.
    if len(candidate) >= 150 and "\n" in candidate:
        LOG.info("Recovered %d chars of letter content after stripping prompt leakage", len(candidate))
        return candidate

    LOG.warning("Could not recover clean letter content from leaky response")
    return ""


def _rewrite_casual_closing(text: str) -> str:
    """Replace casual closing sentences in the final paragraph with a vetted line.

    Runs after retry exhaustion so the docx never ships a banned closer
    even when the LLM keeps producing one. We only touch the FINAL
    paragraph to avoid mangling story-paragraph references to talking
    (e.g., "we talked through the trade-offs at 2 AM").
    """
    if not text:
        return text
    parts = text.rsplit("\n\n", 1)
    if len(parts) != 2:
        return text
    head, final = parts
    if not _CASUAL_CLOSERS_RE.search(final):
        return text
    # Split into sentences; rewrite any sentence that contains the closer.
    sentences = re.split(r"(?<=[\.\?!])\s+", final.strip())
    rewritten = []
    replaced = False
    for s in sentences:
        if _CASUAL_CLOSERS_RE.search(s):
            if not replaced:
                rewritten.append(_VETTED_CLOSER)
                replaced = True
            # Drop subsequent casual sentences entirely.
        else:
            rewritten.append(s)
    return head + "\n\n" + " ".join(rewritten).strip()


def _strip_sign_off(text: str) -> str:
    """Remove any trailing sign-off the LLM added despite being told not to.

    Matches common patterns:
      Best, <name>.
      Best,\n<name>
      Sincerely, ...
      Regards, ...
    Strips the sign-off AND everything after it.
    """
    pattern = re.compile(
        r"\n\s*(Best|Sincerely|Regards|Warm regards|Thank you|Thanks)[,.].*$",
        re.IGNORECASE | re.DOTALL,
    )
    return pattern.sub("", text).rstrip()


# ---------------------------------------------------------------------
# Chain-of-thought meta-commentary detection
# ---------------------------------------------------------------------
# Some "open" reasoning models (Nemotron 3 Super, Qwen3, GLM-4) think out
# loud in plain text rather than inside <think>...</think> tags. When that
# happens, we get "We need to write a cover letter body...", "Let's craft...",
# "Paragraph 1: Opening (2-4 sentences). Something like..." in the docx body.
# These patterns catch that meta-commentary so it never reaches the user.
#
# Patterns are line-anchored, case-insensitive — each represents a sentence
# or line that almost certainly belongs in the model's planning, not in a
# real cover letter.
_MODEL_COT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"^\s*(we|i|let'?s|i'?ll|i'?d|you'?ll|you'?d)\s+(need|should|must|will|have to|are going to|want to)\s+(to\s+)?"
        r"(write|craft|produce|tailor|draft|check|use|avoid|infer|connect|emphasi[sz]e|highlight|aim|target|show|cover|address|include|ensure|make sure|start|open|close|begin|finish|mention|note|consider)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*let'?s\s+(write|craft|draft|check|think|aim|target|see|try|do|go|move|start|use|focus|outline|plan|sketch|consider)\b",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*paragraph\s*\d+\s*[:\-–—]", re.IGNORECASE),
    re.compile(
        r"^\s*(opening|hook|story|connector|closing)\s*paragraph?\s*\(?\d*\s*"
        r"(sentences?|words?)?\)?\s*[:\-–—]",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*(opening|story|closing|hook|connector)\s*[:\-–—]\s*\(", re.IGNORECASE),
    re.compile(r"^\s*check(ing)?\s+(for|that|word|em[\-\s]?dash|prohibited|no)\b", re.IGNORECASE),
    re.compile(r"^\s*something\s+(like|along the lines of)\s*[:\.]?", re.IGNORECASE),
    re.compile(r"^\s*prohibited\s+(words?|phrases?)", re.IGNORECASE),
    re.compile(r"^\s*avoid\s*[: ]", re.IGNORECASE),
    re.compile(r"^\s*(no|use)\s+em\s*[\-–—]?\s*dashes\b", re.IGNORECASE),
    re.compile(r"^\s*now\s+(write|craft|draft|let'?s|to)\b", re.IGNORECASE),
    re.compile(
        r"^\s*(thinking|plan|outline|approach|strategy|draft|note|reasoning|analysis)s?\s*[:\-–—]",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*word\s+count\s*[:\-]?\s*\d", re.IGNORECASE),
    re.compile(r"^\s*make\s+sure\s+(no|to|that)\b", re.IGNORECASE),
    re.compile(r"^\s*(here'?s|here is)\s+(my|the|a)\s+(plan|approach|draft|attempt|outline|version)\b", re.IGNORECASE),
    # Model self-instruction starters
    re.compile(r"^\s*(\d+\s*[\-\.\)]\s*)?(opening|story|closing|hook):\s*", re.IGNORECASE),
    re.compile(r"^\s*(target|aim|goal)\s*[:\-]\s*\d+\s*words?", re.IGNORECASE),
    # Common reasoning-model meta:
    re.compile(r"^\s*(actually|so|hmm|wait|but)\s*[,\.:]\s*(let|we|i)\b", re.IGNORECASE),
    # Bracketed planning markers
    re.compile(r"^\s*[\[\(](draft|plan|note|thinking|approach)[\]\)]", re.IGNORECASE),
]

# Substring markers (not line-anchored) — these always indicate CoT residue
# even mid-paragraph and trigger a hard-fail in validate_cover_letter.
_COT_SUBSTRING_MARKERS: list[str] = [
    "let's craft",
    "let us craft",
    "let's draft",
    "we need to write",
    "we need to tailor",
    "we need to avoid",
    "we need to infer",
    "we'll avoid",
    "we'll use",
    "let's aim",
    "let's see",
    "now let's",
    "now write",
    "let's draft",
    "paragraph 1:",
    "paragraph 2:",
    "paragraph 3:",
    "para 1:",
    "para 2:",
    "para 3:",
    "check for em",
    "check for prohibited",
    "make sure no em",
    "we cannot use em dash",
    "must not use em dash",
    "avoid em dash",
]


def _line_is_cot(line: str) -> bool:
    """Return True if a single line matches any CoT planning pattern."""
    s = line.strip()
    if not s:
        return False
    for pat in _MODEL_COT_PATTERNS:
        if pat.search(s):
            return True
    s_low = s.lower()
    return any(m in s_low for m in _COT_SUBSTRING_MARKERS)


def _strip_cot_meta(raw: str) -> tuple[str, str]:
    """Drop chain-of-thought meta-commentary that "open reasoning" models leak.

    Strategy:
      1. Walk lines from the top — drop the contiguous leading run where ≥40%
         of non-empty lines match a CoT pattern. Stops at the first run of
         "real letter" lines.
      2. Walk lines from the bottom — same logic for trailing planning notes.
      3. Inspect the remainder. If any individual line still matches a CoT
         pattern, the response is unrecoverable.

    Returns (cleaned_text, kind) where kind is one of:
      "none"        — no CoT detected; text unchanged
      "cot_meta"    — recovered some clean letter content after stripping
      "total"       — leakage too severe to recover; cleaned_text is the
                      best-effort residue (caller should retry/fallback)
    """
    if not raw or not raw.strip():
        return "", "none"

    # Quick check — if no line looks like CoT and no substring marker, bail.
    if not any(_line_is_cot(ln) for ln in raw.splitlines()):
        return raw, "none"

    LOG.warning(
        "CoT meta-commentary detected in cover letter (%d chars). Attempting recovery.",
        len(raw),
    )

    paragraphs = re.split(r"\n\s*\n", raw)

    def _block_is_cot(block: str) -> bool:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            return True
        cot = sum(1 for ln in lines if _line_is_cot(ln))
        return cot / len(lines) >= 0.40

    # Drop CoT blocks from the leading + trailing edges.
    while paragraphs and _block_is_cot(paragraphs[0]):
        paragraphs.pop(0)
    while paragraphs and _block_is_cot(paragraphs[-1]):
        paragraphs.pop()

    cleaned = "\n\n".join(p.strip() for p in paragraphs if p.strip())

    # Even after edge-stripping, an interior line may still be CoT.
    interior_cot = any(_line_is_cot(ln) for ln in cleaned.splitlines())

    word_count = len(cleaned.split())
    has_breaks = "\n\n" in cleaned

    if cleaned and word_count >= 120 and has_breaks and not interior_cot:
        LOG.info(
            "Recovered %d words of clean letter content after stripping CoT meta", word_count,
        )
        return cleaned, "cot_meta"

    LOG.warning(
        "CoT recovery failed (words=%d, breaks=%s, interior_cot=%s); marking total",
        word_count, has_breaks, interior_cot,
    )
    return cleaned, "total"


# ---------------------------------------------------------------------
# Cover-letter validation gate
# ---------------------------------------------------------------------
_BANNED_PHRASE_RE = re.compile(
    r"\b(passionate|thrilled|excited to apply|perfect fit|ideal candidate|"
    r"i\s+am\s+writing\s+to\s+express|i\s+would\s+like\s+to\s+express|"
    r"my\s+name\s+is|it\s+is\s+with\s+great)\b",
    re.IGNORECASE,
)
_WEAK_OPENING_RE = re.compile(
    r"^\s*(I am writing|I would like|My name is|It is with|Dear)\b",
    re.IGNORECASE,
)
_PLACEHOLDER_TOKENS = ("[ ]", "<<", ">>", "TODO", "XXX", "TBD", "{{", "}}")

# Casual closers that read as bot-generated in a job application.
# Detected case-insensitively; if any appears in the final paragraph,
# treat it as a validation failure and trigger retry. If retries are
# exhausted, _rewrite_casual_closing replaces the offending sentence.
_CASUAL_CLOSERS_RE = re.compile(
    r"\b(let'?s\s+talk|can\s+we\s+talk|i'?d\s+like\s+to\s+talk|"
    r"let\s+me\s+know\s+if|happy\s+to\s+chat|let'?s\s+chat)\b[\.\?!]?",
    re.IGNORECASE,
)
_VETTED_CLOSER = "I'd welcome the chance to discuss this further."


def validate_cover_letter(text: str, *, target_min_words: int = 220,
                          target_max_words: int = 380) -> list[str]:
    """Hard validation gate — returns issue codes, empty list = PASS.

    Used by the retry ladder in write_cover_letter. Any non-empty result
    triggers a regenerate (or, after exhausted retries, the placeholder
    fallback path).
    """
    issues: list[str] = []
    if not text or not text.strip():
        return ["empty"]

    stripped = text.strip()
    word_count = len(stripped.split())
    if word_count < target_min_words:
        issues.append(f"word_count_low:{word_count}")
    if word_count > target_max_words:
        issues.append(f"word_count_high:{word_count}")

    # Need at least 2 blank-line paragraph breaks (3 paragraphs).
    paragraph_breaks = len(re.findall(r"\n\s*\n", stripped))
    if paragraph_breaks < 2:
        issues.append(f"paragraph_count:{paragraph_breaks + 1}")

    # CoT residue
    for ln in stripped.splitlines():
        if _line_is_cot(ln):
            issues.append(f"cot_residue:{ln.strip()[:60]}")
            break  # one is enough

    # Forbidden tokens
    if "—" in stripped:  # em-dash
        issues.append("forbidden_token:em_dash")
    if re.search(r"<\s*(think|thinking|reasoning|analysis|scratchpad|reflection)\b",
                 stripped, re.IGNORECASE):
        issues.append("forbidden_token:thinking_tag")
    if _WEAK_OPENING_RE.match(stripped):
        issues.append("weak_opening")
    if _BANNED_PHRASE_RE.search(stripped):
        issues.append("banned_phrase")

    # Placeholder-text detection (model said "[Company]" verbatim, etc.)
    for token in _PLACEHOLDER_TOKENS:
        if token in stripped:
            issues.append(f"placeholder:{token}")
            break

    # Casual closer in the final paragraph reads as bot-generated.
    final_para = stripped.rsplit("\n\n", 1)[-1] if "\n\n" in stripped else stripped
    if _CASUAL_CLOSERS_RE.search(final_para):
        issues.append("casual_closing")

    # Trailing sign-off remnant — strip pass should have removed but double-check.
    if re.search(r"\n\s*(Best|Sincerely|Regards|Thanks)\s*,?\s*$", stripped, re.IGNORECASE):
        issues.append("signoff_remnant")

    return issues


# Hard-coded suffix appended to the system prompt on retries 2 and 3 of the
# cover-letter retry ladder. Aggressive emphasis works on Nemotron and most
# instruction-tuned models.
_HARDENED_OUTPUT_SUFFIX = (
    "\n\nCRITICAL OUTPUT RULES (override anything that contradicts):\n"
    "1. Output ONLY the final 3-paragraph letter body. Nothing else.\n"
    "2. NO planning text. Do NOT write phrases like 'We need to', 'Let's craft', "
    "'Now write', 'Paragraph 1:', 'Check for em dashes', 'Make sure no em dash', "
    "or any meta-commentary about the letter.\n"
    "3. NO XML tags. No <think>, <thinking>, <reasoning>, <analysis>.\n"
    "4. NO restating, summarizing, or analyzing this prompt.\n"
    "5. Begin your response with the FIRST WORD of the OPENING paragraph. "
    "If you find yourself wanting to plan, plan silently and emit only the letter."
)


# Sentinel prefix used by build_cover_letter to render a fail-loud banner.
COVER_LETTER_FAILURE_SENTINEL = "[GENERATION FAILED — review before sending]"


_XML_CONTROL_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")


def _clean_json_strings(obj):
    """Recursively clean all string values in a dict/list.

    Strips em dashes (ATS incompatible) and XML-incompatible control
    characters (NULL bytes, etc.) that cause python-docx/lxml to crash.
    Keeps \t (0x09), \n (0x0A), \r (0x0D) which are valid XML whitespace.
    """
    if isinstance(obj, str):
        return _XML_CONTROL_RE.sub("", _strip_em_dashes(obj))
    if isinstance(obj, dict):
        return {k: _clean_json_strings(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_json_strings(v) for v in obj]
    return obj


def _parse_scores(resp: Any, batch_size: int, start: int) -> list[dict]:
    """Parse a ranking LLM response into [{idx, score, reason}] dicts.

    The prompt asks for ``{"scores": [{idx, score, reason}, ...]}``.
    Different models use slightly different field names — this function
    tries common variants and falls back to enumeration order so a rename
    never causes a silent KeyError.

    Args:
        resp:       Parsed JSON from the LLM (dict or list).
        batch_size: Expected number of items in this batch (for fallback).
        start:      Absolute index offset for this batch.
    """
    # Unwrap the envelope. Handles: {"scores": [...]}, {"rankings": [...]},
    # a bare list, a dict-of-dicts keyed by string index, or a single object.
    raw_items: list | None = None
    if isinstance(resp, list):
        raw_items = resp
    elif isinstance(resp, dict):
        for key in ("scores", "rankings", "results", "jobs", "data"):
            if key in resp and isinstance(resp[key], list):
                raw_items = resp[key]
                break
        if raw_items is None:
            # Single score object at root?
            if "score" in resp:
                raw_items = [resp]
            else:
                # dict-of-dicts: {"0": {score:..., reason:...}, "1": {...}}
                vals = list(resp.values())
                if vals and isinstance(vals[0], dict) and "score" in vals[0]:
                    raw_items = vals
                else:
                    # last resort: first list-of-dicts value
                    for v in resp.values():
                        if isinstance(v, list) and v and isinstance(v[0], dict):
                            raw_items = v
                            break

    LOG.debug(
        "_parse_scores: raw_items count=%s, resp_keys=%s",
        len(raw_items) if isinstance(raw_items, list) else "none",
        list(resp.keys()) if isinstance(resp, dict) else type(resp).__name__,
    )

    if not raw_items:
        LOG.warning("_parse_scores: no score items found; defaulting all to 60")
        return [{"idx": start + i, "score": 60, "reason": "(parse failed)"} for i in range(batch_size)]

    _IDX_FIELDS = ("idx", "index", "id", "job_id", "job_index", "number", "pos", "i", "num")
    _SCORE_FIELDS = ("score", "match_score", "rating", "fit_score", "relevance", "fit")
    _REASON_FIELDS = ("reason", "rationale", "explanation", "note", "comment", "summary")

    def _get(item: dict, candidates: tuple, default=None):
        for key in candidates:
            if key in item:
                return item[key]
        # case-insensitive fallback
        item_lower = {k.lower(): v for k, v in item.items()}
        for key in candidates:
            if key in item_lower:
                return item_lower[key]
        return default

    results: list[dict] = []
    for enum_i, item in enumerate(raw_items):
        if not isinstance(item, dict):
            continue
        raw_idx = _get(item, _IDX_FIELDS)
        score = _get(item, _SCORE_FIELDS, 60)
        reason = _get(item, _REASON_FIELDS, "(no reason)")

        try:
            score = max(0, min(100, int(score)))
        except (TypeError, ValueError):
            score = 60

        if raw_idx is None:
            abs_idx = start + enum_i
            LOG.debug("_parse_scores: item %d missing idx field, using enum pos %d", enum_i, abs_idx)
        else:
            try:
                abs_idx = start + int(raw_idx)
            except (TypeError, ValueError):
                abs_idx = start + enum_i

        results.append({"idx": abs_idx, "score": score, "reason": str(reason)})

    if not results:
        return [{"idx": start + i, "score": 60, "reason": "(parse failed)"} for i in range(batch_size)]

    return results


class Tailor:
    def __init__(
        self,
        task_chains: dict[str, list[LLMProvider]],
        critique_cover_letters: bool = False,
    ):
        """
        Args:
            task_chains: per-task provider chains built by get_task_chains().
                Keys: "ranking", "tailoring", "cover_letter", "critique",
                "answer_questions". Each value is a non-empty list of providers
                in priority order.

                Each LLM call tries providers from index 0 of the relevant chain
                independently — a failure on one job does NOT permanently demote
                the primary for subsequent jobs or steps.

            critique_cover_letters: if True, run an LLM critique+revision pass after
                each successfully generated letter. Costs ~1-2 extra calls per job;
                disable for cost-optimized runs.
        """
        self._chains = task_chains
        self._critique_cover_letters = critique_cover_letters
        # Populated by write_cover_letter — main.py reads this and persists
        # the per-attempt diagnostics to cover_letter.debug.json.
        self.last_letter_debug: dict | None = None

    def _get_chain(self, task: str) -> list[LLMProvider]:
        """Return the provider chain for task, falling back to 'tailoring'."""
        return (
            self._chains.get(task)
            or self._chains.get("tailoring")
            or next(iter(self._chains.values()))
        )

    # -----------------------------------------------------------------
    def rank_jobs(self, jobs: list[dict], user_profile: str) -> list[dict]:
        """Return [{'idx': i, 'score': 0-100, 'reason': '...'}] for each job.

        Batched into one call for cost. jobs is a list of {company, title, desc[:800]}.
        Each batch independently tries the ranking chain from index 0 — a quota
        error on batch N does not permanently demote the primary for batch N+1.
        """
        if not jobs:
            return []

        ranking_chain = self._get_chain("ranking")
        system = (
            "You are a pragmatic internship triage assistant. "
            "Score each job posting 0-100 for how well the candidate fits, "
            "plus a one-sentence reason. Return ONLY a JSON object — no prose.\n"
            "Favor jobs matching the candidate's skills, projects, and experience. "
            "Penalize jobs requiring many years of experience or missing skills."
        )

        BATCH = 25
        all_scored: list[dict] = []
        for start in range(0, len(jobs), BATCH):
            batch = jobs[start:start + BATCH]
            listing = "\n".join(
                f"[{i}] {j['company']} | {j['title']} | {j.get('location','')} "
                f"| {j['desc'][:200]}"
                for i, j in enumerate(batch)
            )
            user_prompt = (
                f"CANDIDATE PROFILE:\n{user_profile}\n\n"
                f"JOB POSTINGS:\n{listing}\n\n"
                "Return a JSON object with key \"scores\" containing an array. "
                "Each element: {\"idx\": <integer from [idx] above>, "
                "\"score\": <0-100>, \"reason\": <one sentence>}\n"
                "Use exactly the key name \"idx\" (not \"index\", not \"id\").\n"
                "Example output:\n"
                "{\"scores\": [{\"idx\": 0, \"score\": 82, \"reason\": \"Strong ML match.\"}, "
                "{\"idx\": 1, \"score\": 45, \"reason\": \"Requires C++ skills not listed.\"}]}"
            )
            try:
                resp = try_chain(
                    ranking_chain,
                    lambda p, _u=user_prompt: p.json_call(system, _u, max_tokens=3000),
                    task_name="ranking",
                )
                all_scored.extend(_parse_scores(resp, batch_size=len(batch), start=start))
            except Exception as e:
                LOG.warning("ranking batch failed on all providers: %s (scoring all 60)", e)
                for i in range(len(batch)):
                    all_scored.append({"idx": start + i, "score": 60, "reason": "(rank failed)"})

        return all_scored

    # -----------------------------------------------------------------
    def tailor_resume(
        self,
        master_resume: dict,
        job: dict,
        stories: list | None = None,
        guidelines: list | None = None,
        *,
        quality_tier: str = "standard",
    ) -> dict:
        """Delegate to the self-correcting LangGraph pipeline.

        The graph runs: tailor → keyword_audit → [keyword_fix?] → critique → [revise × ≤2?]
        All post-processing guarantees (_ensure_core_experience, etc.) are applied
        inside the graph after each step that produces a new resume JSON.

        Args:
            quality_tier: "standard" routes through the fast `tailoring` chain
                (deepseek-v4-flash by default). "premium" routes through
                `tailoring_premium` (also v4-flash by default; can be set to the
                deepseek-v4-pro reasoning model) for top-N ranked jobs. main.py
                decides which tier each job uses.

        Populates self.last_tailor_metrics with per-step bullet-band counts,
        line_fitter stats, and total wall-clock seconds. main.py serializes
        this to pipeline_metrics.json alongside resume.json.
        """
        from .tailor_graph import run_tailor_graph
        chain_key = "tailoring_premium" if quality_tier == "premium" else "tailoring"
        metrics: dict = {}
        result = run_tailor_graph(
            master_resume, job,
            tailor_chain=self._get_chain(chain_key),
            critique_chain=self._get_chain("critique"),
            stories=stories,
            guidelines=guidelines,
            metrics_sink=metrics,
        )
        self.last_tailor_metrics = metrics
        return result

    # -----------------------------------------------------------------
    def write_cover_letter(
        self,
        source: dict,
        job: dict,
        user: dict,
        bio: str,
        stories: list[dict],
        example_letter: str | None = None,
        guidelines: list[dict] | None = None,
        *,
        profile: dict | None = None,
        critique: bool | None = None,
    ) -> str:
        """Write a personal, story-driven cover letter grounded in real experience.

        The letter has three parts:
          1. A hook paragraph: something specific about the company/role, not generic.
          2. A story paragraph: the single strongest matching story told concretely.
          3. A connector + close: one sentence linking the story to the role, one
             sentence expressing interest in talking.

        The sign-off is added by the docx builder — do NOT include it here.

        Args:
            critique: per-call override for the constructor-level critique flag.
                main.py passes True for the top-N ranked jobs so they get an
                extra LLM polish pass while skipping the cost for tail jobs.
        """
        if not stories:
            best_story_block = "(no stories available — write from the bio alone)"
        elif len(stories) == 1:
            best = stories[0]
            best_story_block = (
                f"STORY — the spine of the letter:\n"
                f"Title: {best.get('title','')}\n"
                f"One-liner: {best.get('one_liner','')}\n\n"
                f"{best.get('body','')}\n"
            )
        else:
            # Present the matched stories as CANDIDATES (ranked best-first) and
            # let the letter anchor in whichever genuinely fits THIS role. This
            # stops every AI/ML JD from reusing the same top story verbatim — a
            # backend/infra JD should be able to lead with an infra story instead.
            # The letter anchors in exactly ONE story, so only the top candidate
            # needs its full body. The rest are shown as title + one-liner + a
            # short excerpt — enough to let the model pick a better-fitting lower
            # candidate, without shipping 8-12 KB of story text (and re-shipping
            # it across the retry/critique ladder).
            best_story_block = (
                "CANDIDATE STORIES (ranked best-first). Anchor the letter in the "
                "ONE that best fits this specific role — usually the first, but "
                "pick a lower one if it maps more directly to the JD. Story 1 is "
                "shown in full; the rest are summarised — if one of them fits "
                "better, lead with it and tell it from its one-liner + excerpt:\n\n"
            )
            for i, s in enumerate(stories, 1):
                body = (s.get("body") or "").strip()
                if i > 1:
                    body = body[:STORY_CANDIDATE_CAP]
                best_story_block += (
                    f"[Story {i}] {s.get('title','')}\n"
                    f"One-liner: {s.get('one_liner','')}\n\n"
                    f"{body}\n\n"
                )

        example_block = ""
        if example_letter:
            example_block = (
                "\nSTYLE ANCHOR (a past letter — match the voice, not the content):\n"
                f"{example_letter[:1200]}\n"
            )

        # Guideline injection — pulls the top-k matched guideline docs (e.g.,
        # cover_letter_hook_specificity.md, recruiter_first_10_seconds.md).
        # Each guideline body is capped at 600 chars so prompts stay under
        # the model's typical 8K-token context budget.
        guidelines_block = ""
        if guidelines:
            guidelines_block = "\nCOVER LETTER GUIDELINES (apply as quality gates):\n"
            for g in guidelines[:3]:
                chunk = (g.get("body") or "").strip()[:600]
                if chunk:
                    guidelines_block += f"{chunk}\n\n"

        first_name = user["full_name"].split()[0]
        desc_text = (job.get("description") or "").strip()
        sparse_desc = len(desc_text) < 200

        # Positioning guard (mirrors the resume's identity rules so the two
        # documents agree on level). Without this the letter freely re-levels
        # the candidate to fit the JD — e.g. calling a full-time role an
        # "internship" for an intern posting, contradicting the resume.
        positioning_block = ""
        if profile:
            titles = ", ".join(profile.get("identity_titles") or []) or "their real title"
            seniority = profile.get("seniority", "professional")
            positioning_block = (
                f"POSITIONING (must match the resume's level): the candidate's real "
                f"identity is {titles} ({seniority}). Refer to their roles exactly as "
                f"they are — never rename, re-title, or re-level them to fit this "
                f"posting. A full-time role is NEVER an 'internship', even when "
                f"applying to an intern role.\n\n"
            )

        if sparse_desc:
            hook_guidance = (
                "Opening paragraph (2-4 sentences): the job description is minimal, "
                "only the company name and role title are known. Do not fabricate JD "
                "specifics. Instead open with an honest inference about the company's "
                "domain from its name and the role title, then connect that domain to "
                "the story. 'I know [Company] works in X space, and the problem I kept "
                "running into was...' beats vague enthusiasm. Never open with your own "
                "credentials or school.\n\n"
            )
        else:
            hook_guidance = (
                "Opening paragraph (2-4 sentences): open with something concrete about "
                "this specific company or role — a problem the role exists to solve, "
                "something from the job description that caught your attention, or a "
                "direct connection between the company's work and the story you're about "
                "to tell. Never open with 'I've been following your work' or 'I am "
                "writing to express my interest.' Never open with your own credentials. "
                "The first sentence should make the reader think this person actually "
                "read our posting.\n\n"
            )

        system = (
            # Absolute output rules — emphatic up-front, before anything else.
            "ABSOLUTE OUTPUT RULES (these override every other instruction):\n"
            "- Your ENTIRE response is the 3-paragraph cover letter body. Nothing else.\n"
            "- The first character of your response is the first letter of the opening "
            "paragraph. Do not preface with 'Here is the letter', 'Sure', or any header.\n"
            "- DO NOT write meta-commentary like 'We need to', 'Let's craft', 'Let's "
            "aim', 'Now write', 'Paragraph 1:', 'Check for em dashes', 'Make sure no...', "
            "'Something like:', 'Draft:', or any planning text. Plan silently.\n"
            "- DO NOT use <think>, <thinking>, <reasoning>, or any XML/HTML tags.\n"
            "- DO NOT label sections. DO NOT restate or analyze this prompt. DO NOT add "
            "a sign-off — the docx renderer adds one.\n\n"

            "You write cover letters as direct personal emails, not formal application "
            "documents. Write to a specific person at a specific company.\n\n"

            "How to write each paragraph:\n\n"
            + hook_guidance +

            "Story paragraph (4-7 sentences, aim for 5-6): tell one story directly. "
            "Start from the context — what the problem or situation was. Then what you "
            "built or did, with specific technical details (name the tech, the architecture "
            "decision, the non-obvious choice). Then what made it hard or non-trivial. "
            "Then the concrete outcome with the real metric or impact. Do not introduce "
            "the story with 'One project that comes to mind is' or 'At my previous role.' "
            "Just start telling it.\n\n"

            "Closing paragraph (3-4 sentences): draw one explicit line between what the "
            "story demonstrated and what this role needs. Name the specific skill or "
            "judgment the story showed, then name the thing from the job description it "
            "maps to. Add one sentence about what specifically draws you to this company "
            "or problem (from the JD, not generic enthusiasm). Close with one professional "
            "sentence offering a conversation, e.g., 'I'd welcome the chance to discuss "
            "how this maps to your team's work.' NEVER end with 'Let's talk', 'Can we talk', "
            "'I'd like to talk', 'Let me know if', 'Happy to chat', or any equivalent casual "
            "phrasing — these read as bot-generated. No 'I believe I would be a great fit.' "
            "No recap of your resume.\n\n"

            "Style rules: no em dashes, use commas or semicolons; no 'passionate', "
            "'thrilled', or 'excited to apply'; no prose skill lists; no 'perfect fit' "
            "or 'ideal candidate'; no paragraph openers like 'Furthermore' or 'Moreover'; "
            "no bullet points or markdown; contractions are fine; 220-380 words total. "
            "Three paragraphs separated by a SINGLE blank line."
        )

        user_prompt = (
            f"Candidate voice, how {first_name} writes (absorb the tone, do not "
            f"reproduce this section):\n{(bio or '')[:COVER_LETTER_BIO_CAP]}\n\n"
            f"Story material:\n{best_story_block}\n"
            f"{example_block}"
            f"{guidelines_block}"
            f"{positioning_block}"
            f"Job:\n"
            f"Company: {(job.get('company') or '')}\n"
            f"Title: {(job.get('title') or '')}\n"
            f"Location: {job.get('location', '')}\n\n"
            f"Job description:\n{(job.get('description') or '')[:3200]}\n\n"
            f"BINDING: You MUST anchor the STORY paragraph in the single "
            f"best-fitting story from the Story material above (the candidate's "
            f"real work). Do not invent projects, stories, or experiences not "
            f"present in the Story material. If no story fits this role cleanly, "
            f"lead with the transferable skill the strongest story showed "
            f"(judgment, system design, debugging instincts) rather than forcing a "
            f"company-specific hook. NEVER claim experience the candidate doesn't "
            f"have, and NEVER name technologies not mentioned in the story material.\n\n"
            f"Write the letter now. Start directly with the first sentence of the "
            f"opening paragraph. No label, no 'Dear', no sign-off, no planning text, "
            f"no em dashes. Do not open with {first_name}'s credentials or school name."
        )

        critique_this_call = (
            critique if critique is not None else self._critique_cover_letters
        )
        return self._cover_letter_retry_ladder(
            system, user_prompt, self._get_chain("cover_letter"),
            critique=critique_this_call,
        )

    def _cover_letter_retry_ladder(
        self, system: str, user_prompt: str, cl_chain: list[LLMProvider],
        *, critique: bool = False,
    ) -> str:
        """3-attempt retry ladder for cover-letter generation.

        Attempt 1: cl_chain[0] @ max_tokens=1400 — plain prompt
        Attempt 2: cl_chain[0] @ max_tokens=1800 — hardened suffix appended
        Attempt 3: cl_chain[1] @ max_tokens=1400 — hardened suffix (if available)

        Each call for a given job starts fresh from cl_chain[0] — a fallback used
        on one job does NOT demote the primary for the next job's letter.

        Once validation passes, an optional critique step grades the letter and
        triggers ONE revision pass if quality is weak (score < 7).

        Returns:
          - clean letter text (em-dashes / sign-off stripped) on success
          - sentinel-prefixed string on total failure (build_cover_letter
            renders this as a red 'DO NOT SEND' banner)

        Updates ``self.last_letter_debug`` with attempt-by-attempt diagnostics
        so main.py can persist a postmortem JSON snapshot.
        """
        primary = cl_chain[0]
        fallback = cl_chain[1] if len(cl_chain) > 1 else None

        debug_attempts: list[dict] = []
        best_recovered: str = ""

        attempts = [
            {"provider": primary,                      "max_tokens": 1600, "use_hardened": False},
            {"provider": primary,                      "max_tokens": 2000, "use_hardened": True},
            {"provider": fallback or primary,          "max_tokens": 1600, "use_hardened": True},
        ]

        for i, plan in enumerate(attempts, start=1):
            provider = plan["provider"]

            # Skip attempt 3 if there's no real fallback (same as primary — not useful)
            if i == 3 and fallback is None:
                LOG.debug("Cover letter attempt 3 skipped: no fallback provider in cl_chain")
                debug_attempts.append({"attempt": i, "skipped": True, "reason": "no_fallback_provider"})
                continue

            sys_prompt = system + (_HARDENED_OUTPUT_SUFFIX if plan["use_hardened"] else "")

            try:
                raw = provider.text_call(sys_prompt, user_prompt, max_tokens=plan["max_tokens"])
            except Exception as e:
                LOG.warning("Cover letter attempt %d (%s) failed: %s", i, provider.name, e)
                debug_attempts.append({
                    "attempt": i, "provider": provider.name, "error": str(e)[:200],
                })
                continue

            # Post-process: strip echoed prompts → CoT meta → em-dashes → sign-off.
            cleaned, prompt_kind = raw, "none"
            recovered = _strip_prompt_leakage(raw)
            if recovered is not None:
                cleaned = recovered if recovered else ""
                prompt_kind = "prompt_echo"

            cleaned, cot_kind = _strip_cot_meta(cleaned)
            cleaned = _strip_sign_off(_strip_em_dashes(cleaned))
            # Deterministically rewrite casual closers ("Let's talk." etc.) so
            # validation focuses on issues that actually need a model retry.
            cleaned = _rewrite_casual_closing(cleaned)

            issues = validate_cover_letter(cleaned)

            debug_attempts.append({
                "attempt": i,
                "provider": provider.name,
                "max_tokens": plan["max_tokens"],
                "hardened": plan["use_hardened"],
                "raw_chars": len(raw),
                "cleaned_chars": len(cleaned),
                "prompt_leakage_kind": prompt_kind,
                "cot_kind": cot_kind,
                "issues": issues,
            })

            if not issues:
                LOG.info("Cover letter passed validation on attempt %d (provider=%s)",
                         i, provider.name)
                if critique:
                    final_text, critique_info = self._critique_and_maybe_revise(
                        cleaned, system, user_prompt,
                    )
                else:
                    final_text = cleaned
                    critique_info = {"skipped": True, "reason": "critique_disabled"}
                debug_attempts.append({"attempt": "critique", **critique_info})
                self.last_letter_debug = {"status": "ok", "attempts": debug_attempts}
                return final_text

            LOG.warning("Cover letter attempt %d had issues: %s", i, issues[:5])
            if len(cleaned) > len(best_recovered):
                best_recovered = cleaned

        # All attempts failed validation — return sentinel for fail-loud banner.
        LOG.error("Cover letter generation failed all %d attempts; emitting placeholder",
                  len(attempts))
        self.last_letter_debug = {"status": "placeholder", "attempts": debug_attempts}
        body = best_recovered.strip() or "(no recoverable content)"
        return f"{COVER_LETTER_FAILURE_SENTINEL}\n\n{body}"

    def _critique_and_maybe_revise(
        self, letter: str, system: str, user_prompt: str,
    ) -> tuple[str, dict]:
        """Score the letter via LLM; if score <7, run ONE revision pass.

        Uses the critique chain for the score call (cheap, small output) and
        the cover_letter chain for the revision (creative, larger output).
        Returns (final_text, debug_info).
        """
        critique_chain = self._get_chain("critique")
        cl_chain = self._get_chain("cover_letter")

        critique_system = (
            "You are a critical reviewer of cover letters. Score the letter on a 1-10 "
            "scale based on these dimensions:\n"
            "  - opening_specificity: does the first sentence reference something "
            "concrete about THIS company/role, or is it generic?\n"
            "  - story_concreteness: does the story have real metrics, technical "
            "specifics, and a real outcome, or is it vague?\n"
            "  - jd_tie_in: does the closing paragraph draw an explicit line "
            "between the story and what the job description asks for?\n"
            "  - voice_authenticity: does it sound like a real engineer wrote it, "
            "or like a generic AI template?\n"
            "  - professional_closing: the final sentence must offer a conversation "
            "professionally (e.g., 'I'd welcome the chance to discuss'). Casual "
            "phrasings like 'Let's talk', 'Can we talk', 'I'd like to talk', "
            "'Let me know if' are FAILURES — flag in issues.\n"
            "  - company_named: the company name appears at least once in the body. "
            "If not, flag in issues and require_fix.\n"
            "  - story_anchored: the body actually tells the supplied PRIMARY STORY "
            "with concrete details, not a generic platitude.\n\n"
            "Return ONLY a JSON object with keys: score (1-10 integer overall), "
            "issues (list of short strings, max 3), required_fixes (list of short "
            "specific instructions, max 3, empty if score>=7)."
        )
        critique_user = (
            f"Cover letter to grade:\n\n{letter}\n\n"
            "Score 1-10 and list at most 3 required_fixes if score < 7."
        )

        try:
            critique = try_chain(
                critique_chain,
                lambda p: p.json_call(critique_system, critique_user, max_tokens=400),
                task_name="cl_critique",
            )
        except Exception as e:
            LOG.debug("Cover letter critique skipped (provider error): %s", e)
            return letter, {"skipped": True, "reason": str(e)[:100]}

        score = int(critique.get("score", 7) or 7)
        fixes = critique.get("required_fixes") or []
        issues = critique.get("issues") or []

        if score >= 7 or not fixes:
            return letter, {
                "score": score, "issues": issues, "fixes": fixes, "revised": False,
            }

        LOG.info("Cover letter score=%d, attempting revision: %s", score, fixes[:2])

        repair_instructions = "\n".join(
            f"- {fix}" for fix in fixes[:3] if isinstance(fix, str)
        )
        revise_system = system + _HARDENED_OUTPUT_SUFFIX + (
            "\n\nThis is a REVISION. The previous draft scored low on these issues:\n"
            f"{repair_instructions}\n"
            "Rewrite the entire letter applying every fix. Same 3-paragraph "
            "structure, same word range (180-320). Output the letter only."
        )
        revise_user = user_prompt + (
            f"\n\nPREVIOUS DRAFT (apply the required fixes to produce a stronger one):\n"
            f"{letter}"
        )

        try:
            revised_raw = try_chain(
                cl_chain,
                lambda p: p.text_call(revise_system, revise_user, max_tokens=1400),
                task_name="cl_revise",
            )
        except Exception as e:
            LOG.warning("Cover letter revision failed: %s", e)
            return letter, {
                "score": score, "issues": issues, "fixes": fixes, "revised": False,
                "revise_error": str(e)[:100],
            }

        revised = revised_raw
        recovered = _strip_prompt_leakage(revised)
        if recovered is not None:
            revised = recovered or ""
        revised, _ = _strip_cot_meta(revised)
        revised = _strip_sign_off(_strip_em_dashes(revised))

        revised_issues = validate_cover_letter(revised)
        if revised_issues:
            LOG.info("Revision had issues, keeping original: %s", revised_issues[:3])
            return letter, {
                "score": score, "issues": issues, "fixes": fixes, "revised": False,
                "revised_issues": revised_issues,
            }

        return revised, {
            "score": score, "issues": issues, "fixes": fixes, "revised": True,
        }

    # -----------------------------------------------------------------
    def answer_questions(
        self,
        questions: list[str],
        job: dict,
        user: dict,
        bio: str,
        stories: list[dict],
        specific_instructions: str = "",
    ) -> list[dict]:
        """Return list of {"question": str, "answer": str}.

        Each answer is 100-200 words, first person, grounded in the candidate's
        stories. Called for the manual application flow when the job posting
        includes additional application questions.
        """
        if not questions:
            return []

        story_block = "\n\n".join(
            f"STORY: {s.get('title', '')}\n"
            f"One-liner: {s.get('one_liner', '')}\n"
            f"{(s.get('body') or '')[:STORY_BODY_CAP]}"
            for s in stories[:3]
        ) or "(no stories available)"

        q_block = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(questions))

        system = (
            "You write concise, specific answers to job application questions. "
            "Each answer is 100-200 words, written in first person, grounded in "
            "real experience from the candidate's stories. Never be generic. "
            "No em dashes (—). No 'passionate', 'thrilled', or 'excited to apply'. "
            "No bullet points. Plain prose only."
        )

        user_prompt = (
            f"CANDIDATE VOICE:\n{bio[:800]}\n\n"
            f"STORY MATERIAL:\n{story_block}\n\n"
            f"JOB: {job.get('company', '')} — {job.get('title', '')}\n"
            f"JD EXCERPT: {(job.get('description') or '')[:1200]}\n\n"
            + (f"SPECIFIC INSTRUCTIONS: {specific_instructions}\n\n" if specific_instructions else "")
            + f"QUESTIONS:\n{q_block}\n\n"
            "Return a JSON object with key \"answers\": a list where each element "
            "has \"question\" (the exact question text) and \"answer\" (100-200 words). "
            "Ground each answer in one of the stories above. Do not use em dashes."
        )

        aq_chain = self._get_chain("answer_questions")
        try:
            result = try_chain(
                aq_chain,
                lambda p: p.json_call(system, user_prompt, max_tokens=2000),
                task_name="answer_questions",
            )
            raw_answers = result.get("answers", [])
            if not isinstance(raw_answers, list):
                raw_answers = []
            out = []
            for i, q in enumerate(questions):
                if i < len(raw_answers):
                    a = raw_answers[i]
                    out.append({
                        "question": a.get("question", q),
                        "answer": _strip_em_dashes(str(a.get("answer", ""))),
                    })
                else:
                    out.append({"question": q, "answer": "(generation failed)"})
            return out
        except Exception as e:
            LOG.warning("answer_questions failed: %s", e)
            return [{"question": q, "answer": "(generation failed)"} for q in questions]
