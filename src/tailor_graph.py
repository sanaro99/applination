"""
Self-correcting resume tailoring pipeline.

Pipeline: tailor -> keyword_audit (pure Python) -> [keyword_fix?] -> critique -> [revise x <=1?] -> done

The keyword_audit step is zero-cost: ats_keywords are extracted inside the tailor
LLM call (as an extra output field), so no separate audit call is needed.

Implemented as plain Python — no LangGraph/LangChain dependency — so it works
on Python 3.14+ without Pydantic v1 compatibility issues.

Public API:  run_tailor_graph(master_resume, job, provider,
                              stories=None, guidelines=None) -> dict
"""
from __future__ import annotations
import json
import logging
import re
from typing import Any

from .providers import LLMProvider
from .providers.factory import is_quota_error
from .tailor import (
    RESUME_CONSTRAINTS,
    CANONICAL_SKILL_GROUPS,
    _normalize_resume_json,
    _ensure_core_experience,
    _ensure_core_skills,
    _dedupe_projects_vs_experience,
    _scrub_summary_fabrications,
    _clean_json_strings,
)
from .profile import derive_profile

LOG = logging.getLogger(__name__)

KEYWORD_COVERAGE_THRESHOLD = 0.65   # 65% of JD keywords must appear in resume
MAX_REVISIONS = 1                    # max critique -> revise cycles per job

# Bullet line-fit bands live in line_fitter.py and are font-aware: they are
# recomputed by line_fitter.configure_for_font() at run start. We reference the
# module (not import the constants by value) so every read picks up the bands
# for the currently-configured render font.
from . import line_fitter as _lf  # noqa: E402
from .line_fitter import fit_bullets_to_bands  # noqa: E402


# ---------------------------------------------------------------------------
# Pipeline state (plain dict — no TypedDict, no Pydantic)
# ---------------------------------------------------------------------------

def _make_state(
    master_resume: dict,
    job: dict,
    stories: list,
    guidelines: list,
) -> dict:
    return {
        "master_resume": master_resume,
        "job": job,
        "profile": derive_profile(master_resume),
        "tailored_json": {},
        "audit": {},
        "critique": {},
        "revision_count": 0,
        "keyword_fixed": False,
        "stories": stories,
        "guidelines": guidelines,
        # Observability — populated by _log_bullet_bands at each step so the
        # final pipeline_metrics.json reflects the per-stage health.
        "metrics": {
            "steps": [],
            "started_at": __import__("time").time(),
            "llm_calls": 0,
        },
    }


def _log_bullet_bands(state: dict, step_name: str) -> None:
    """Snapshot the bullet-band breakdown after a pipeline step.

    Appends an entry to state['metrics']['steps'] AND emits a log line so the
    user sees in real time which step degraded or improved the resume.
    """
    from .line_fitter import classify as _classify
    tailored = state.get("tailored_json") or {}
    counts = {"single": 0, "double": 0, "forbidden": 0, "short": 0, "overlong": 0}
    for section in ("experience", "projects"):
        for entry in tailored.get(section, []) or []:
            for b in entry.get("bullets", []) or []:
                if isinstance(b, str):
                    counts[_classify(len(b))] = counts.get(_classify(len(b)), 0) + 1

    LOG.info(
        "bullet-bands [stage=%s]: %d single, %d double, %d forbidden, %d short, %d overlong",
        step_name, counts["single"], counts["double"], counts["forbidden"],
        counts["short"], counts["overlong"],
    )
    state.setdefault("metrics", {}).setdefault("steps", []).append({
        "name": step_name,
        "bullets": dict(counts),
    })


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _apply_guarantees(
    tailored: Any, master: dict, *, fallback: dict | None = None, profile: dict | None = None,
) -> dict:
    """Enforce non-negotiable constraints after every LLM step."""
    if not isinstance(tailored, dict) or not tailored:
        LOG.warning(
            "_apply_guarantees: LLM returned %s instead of dict -- using fallback",
            type(tailored).__name__,
        )
        return fallback if isinstance(fallback, dict) and fallback else {}
    if profile is None:
        profile = derive_profile(master)
    tailored = _normalize_resume_json(tailored)
    tailored = _ensure_core_experience(tailored, master, profile)
    tailored = _ensure_core_skills(tailored, master)
    tailored = _dedupe_projects_vs_experience(tailored)
    tailored = _scrub_summary_fabrications(tailored, profile)
    tailored = _clean_json_strings(tailored)
    return tailored


def _safe_desc(job: dict, limit: int) -> str:
    return (job.get("description") or "")[:limit]


def _safe_company(job: dict) -> str:
    return job.get("company") or ""


def _safe_title(job: dict) -> str:
    return job.get("title") or ""


def _format_master_skill_pool(master: dict) -> str:
    raw = master.get("skills") or {}
    lines = []
    if isinstance(raw, dict):
        for group, items in raw.items():
            if isinstance(items, list) and items:
                lines.append(f"  {group}: {', '.join(str(i) for i in items)}")
    elif isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict):
                g = entry.get("group", "")
                items = entry.get("items") or []
                if items:
                    lines.append(f"  {g}: {', '.join(str(i) for i in items)}")
    return "\n".join(lines) if lines else "(see master resume above)"


_TOKEN_RE = re.compile(r"[a-z0-9+#.]+")


def _rank_projects_by_jd(projects: list[dict], jd_text: str) -> list[dict]:
    """Reorder master projects most-relevant-first for THIS job.

    The LLM is handed the master verbatim and tends to pick the same
    flashy projects every time regardless of role. Pre-sorting by simple
    token overlap (project name + tech + bullets vs the JD) surfaces the
    genuinely relevant work — e.g. an infra project for a backend JD instead
    of an ML demo — without any LLM call. Order-only; nothing is dropped, so
    it can never hide truthful content. Stable: ties keep master order.
    """
    if not projects:
        return projects
    jd_tokens = set(_TOKEN_RE.findall((jd_text or "").lower()))
    if not jd_tokens:
        return projects

    def _score(p: dict) -> int:
        text = " ".join([
            str(p.get("name", "")),
            str(p.get("tech", "")),
            " ".join(p.get("bullets_all") or []),
        ]).lower()
        return len(set(_TOKEN_RE.findall(text)) & jd_tokens)

    indexed = list(enumerate(projects))
    indexed.sort(key=lambda iv: (-_score(iv[1]), iv[0]))
    return [p for _, p in indexed]


# ---------------------------------------------------------------------------
# Node implementations (plain callables, state is a regular dict)
# ---------------------------------------------------------------------------

def _run_tailor(state: dict, provider: LLMProvider) -> None:
    master = state["master_resume"]
    job = state["job"]
    stories = state.get("stories") or []
    guidelines = state.get("guidelines") or []
    c = RESUME_CONSTRAINTS

    core_skills = master.get("core_skills") or []
    ats_adjacent = master.get("ats_adjacent_skills") or []
    canonical_groups = ", ".join(f'"{g}"' for g in CANONICAL_SKILL_GROUPS)
    skill_pool = _format_master_skill_pool(master)

    # Candidate identity is derived from the master resume (see src/profile.py),
    # never hardcoded — so the IDENTITY / seniority / closing-credential prompt
    # rules below are truthful for whoever owns this install.
    profile = state.get("profile") or derive_profile(master)
    titles = profile.get("identity_titles") or ["professional"]
    primary_title = profile.get("primary_title") or titles[0]
    identity_noun_options = ", ".join(f"'{t.lower()}'" for t in titles)
    if len(titles) <= 2:
        titles_human = " and ".join(titles)
    else:
        titles_human = ", ".join(titles[:-1]) + ", and " + titles[-1]
    seniority = profile.get("seniority", "professional")
    edu_close = profile.get("education_close") or ""
    if seniority == "professional":
        seniority_rule = (
            "    NEVER label the candidate an 'intern', 'new grad', or 'student' in "
            "the identity — they are an experienced professional.\n"
        )
    elif seniority == "new-grad":
        seniority_rule = (
            "    The candidate is an early-career / new-grad applicant — do not "
            "inflate to senior or staff titles they have not held.\n"
        )
    else:  # student
        seniority_rule = (
            "    The candidate is a student — it is fine to present them as a "
            "student where natural, but lead with their strongest real skills.\n"
        )
    edu_close_rule = (
        "  - Close with the strongest credential the JD cares about"
        + (f" (e.g. {edu_close})" if edu_close else "")
        + ".\n"
    )

    system = (
        "You are an elite ATS-focused resume writer. Your output is consumed by both "
        "Applicant Tracking Systems (keyword-matched) and human recruiters (skim-read in "
        "30 seconds). Produce a JSON resume that:\n"
        "  1. Maximizes keyword overlap with the JD using ONLY truthful content from the MASTER.\n"
        "  2. Reads like it was hand-written for THIS job, not a generic resume.\n"
        "  3. Fills the page densely — use the upper end of every length budget.\n\n"

        "==== HARD GROUNDING RULE ====\n"
        "Every claim must trace back to something in the MASTER. Rephrase, reorder, "
        "re-emphasize freely, but do NOT invent companies, titles, dates, metrics, "
        "technologies, or projects that are not in the MASTER. Do NOT infer "
        "plausible specifics either: a tool the candidate 'probably' used, a likely "
        "team size, a round-number metric. If the MASTER does not state it, it does "
        "not exist. When a JD keyword has no truthful basis in the MASTER, OMIT it "
        "rather than stretch to cover it. A shorter true resume beats a padded "
        "invented one.\n\n"

        "==== SUMMARY: rewrite, do NOT echo ====\n"
        "Compose a NEW 2-3 sentence summary (DO NOT copy any summary_option verbatim):\n"
        f"  - IDENTITY: the candidate's REAL job titles are {titles_human}. "
        f"The opening identity NOUN must be one of: {identity_noun_options}. You MAY "
        "prepend ONE JD-relevant focus adjective drawn from their real work — e.g. "
        f"'Backend {primary_title.lower()}', 'AI-focused {primary_title.lower()}' — but "
        "the NOUN must stay one of the real titles above.\n"
        "    NEVER use the JD's job title as the candidate's identity. Example: for a "
        "'Product Marketing Engineer' JD, do NOT write 'Product Marketing Engineer' — "
        f"write the candidate's real title ({primary_title}). Likewise never invent a "
        "title the MASTER does not support (e.g. 'Forward Deployed Engineer', "
        "'Applied Scientist', 'Product Manager').\n"
        + seniority_rule +
        "  - Mirror 2-4 specific hard-skill keywords from the JD using the JD's exact "
        "wording (e.g., if JD says 'LLM inference pipelines', write 'LLM inference "
        "pipelines' not 'large language models'). The summary must read as written for "
        "THIS specific role, not a generic profile.\n"
        "  - TRUTHFULNESS: do NOT claim domain experience the master doesn't show. If "
        "the JD demands a domain the master does not cover, lead with the candidate's "
        "strongest real, transferable experience instead of fabricating domain "
        "expertise.\n"
        "  - TENURE HONESTY: a duration like 'N+ years' describes the candidate's "
        "OVERALL experience, and MUST attach only to the BROAD scope of what they did "
        "across that whole span, never to a single specialized or recent activity. A "
        "role usually spans several kinds of work (e.g. reliability/support AND a "
        "later AI build); the years count covers ALL of it, not just the JD-relevant "
        "slice. FORBIDDEN: '4+ years building LLM agents' / '4+ years building "
        "production AI systems' when AI/LLM work is only one part of the tenure. "
        "ALLOWED: bind the years to the broad role ('4+ years in software engineering "
        "and reliability') and mention the specialized/recent work as a SEPARATE "
        "clause without its own duration ('...including recent LLM agent work' or "
        "'Built an LLM-powered platform...'). If the master does not show how long a "
        "specific activity lasted, state that activity WITHOUT any years figure. Do "
        "not front-load a specialty adjective onto the years either ('4+ years of "
        "AI-focused engineering' is fine; '4+ years of building LLM agents' is not).\n"
        "  - Name ONE quantified flagship outcome from the MASTER.\n"
        + edu_close_rule +
        f"  - Length: 220-{c['summary_max_chars']} chars. Aim for upper end.\n\n"

        "==== SKILLS: DENSITY IS MANDATORY ====\n"
        f"Use {c['skills_groups_max']} groups. "
        f"MINIMUM 25 skills, TARGET 35-42 (budget cap: {c['skills_max_total']}).\n"
        "Leaving budget unused is a critical defect — fewer than 25 skills will FAIL "
        "ATS filters at most companies. Fill every available slot.\n"
        f"Group names MUST be exactly from: {canonical_groups}. No snake_case.\n\n"
        "Selection order:\n"
        "  Step 1 (MANDATORY): include ALL core skills regardless of JD:\n"
        f"    {', '.join(core_skills) if core_skills else '(none)'}\n"
        "  Step 2 (JD MIRROR): add every hard-skill keyword from the JD the candidate "
        "has experience with, using the JD's exact spelling.\n"
        "  Step 3 (ATS-ADJACENTS): from this allow-list, add items the JD calls for "
        "if candidate has a clear adjacent:\n"
        f"    {', '.join(ats_adjacent) if ats_adjacent else '(none)'}\n"
        "  Step 4 (FILL TO BUDGET — REQUIRED): after steps 1-3 you likely have 10-15 "
        "skills. You MUST add more from the MASTER SKILL POOL until you reach at "
        "least 25 total. Pull ALL relevant items. Prefer breadth over repetition:\n"
        f"{skill_pool}\n\n"

        "==== EXPERIENCE ====\n"
        f"At most {c['experience_max_items']} entries. "
        f"Each MUST have EXACTLY {c['experience_bullets_per_item']} bullets.\n\n"
        "BULLET QUALITY BAR — all bullets must meet ALL of these:\n"
        f"  LINE-FILL: a bullet renders one or two lines (~{_lf.LINE_CHARS} chars "
        f"per printed line). Pick ONE mode per bullet and FILL the line:\n"
        f"    SINGLE-LINE  : {_lf.SINGLE_TARGET}-{_lf.SINGLE_MAX} chars. Pack the "
        f"line nearly edge-to-edge; anything under {_lf.SINGLE_TARGET} leaves "
        f"visible empty space and looks lazy.\n"
        f"    DOUBLE-LINE  : {_lf.DOUBLE_MIN}-{_lf.DOUBLE_MAX} chars. Fills both "
        f"lines almost edge-to-edge.\n"
        f"  FORBIDDEN ZONE: {_lf.FORBIDDEN_LO}-{_lf.FORBIDDEN_HI} chars — wraps to "
        f"a second line that stays mostly empty. If a draft lands here, EITHER "
        f"trim to {_lf.SINGLE_TARGET}-{_lf.SINGLE_MAX} OR expand with concrete "
        f"detail (technique, scope, outcome) to reach {_lf.DOUBLE_MIN}+.\n"
        "  Count chars before submitting. The line budget is unforgiving.\n"
        "  PAR FORMAT: Problem/context (brief) -> Action (what YOU built/changed) -> "
        "Result (metric or outcome). Example: 'Redesigned RAG ingestion pipeline for "
        "50K+ docs corpus, replacing ad-hoc scripts with LangChain agents, cutting "
        "processing time 70% and enabling real-time updates.'\n"
        "  ACTION VERBS: strong past-tense, varied. Never repeat the same verb twice "
        "in one role. Use: Engineered, Architected, Designed, Built, Shipped, Scaled, "
        "Reduced, Optimized, Led, Owned, Automated, Migrated, Deployed, Refactored.\n"
        "  METRICS: keep all concrete metrics from master (95%, 50K docs, $10B+, "
        "200+ microservices). If a bullet has no metric, add scope (team size, "
        "service count, data volume) ONLY when the MASTER states it. Never invent a "
        "number to fill the gap; a bullet with no metric is fine.\n"
        "  JD KEYWORDS: mirror 1-2 JD hard-skill keywords per bullet WHERE TRUTHFUL.\n\n"

        "==== PROJECTS ====\n"
        f"At most {c['projects_max_items']} entries, "
        f"{c['projects_bullets_per_item']} bullets each.\n"
        "Select projects by JD domain match. A PROJECT PRIORITY list for THIS "
        "role is provided after the job description (most relevant first); prefer "
        "those, but pick a lower-priority one if it clearly maps better to the "
        "JD's tech stack/domain.\n"
        f"Apply the same LINE-FILL and PAR FORMAT rules as experience bullets — "
        f"either {_lf.SINGLE_TARGET}-{_lf.SINGLE_MAX} chars (a full single line) "
        f"OR {_lf.DOUBLE_MIN}-{_lf.DOUBLE_MAX} chars (full two lines). Never the "
        f"{_lf.FORBIDDEN_LO}-{_lf.FORBIDDEN_HI} forbidden zone. No stubs.\n\n"

        "==== EDUCATION ====\n"
        f"Up to {c['education_max_items']} entries. Always include the candidate's "
        "highest / most recent degree. Coursework: 4-6 courses mapped to JD, "
        "comma-joined.\n\n"

        "==== ATS-SAFE FORMATTING ====\n"
        "Plain ASCII only (en-dash - OK for date ranges). No emojis, tables, images.\n\n"

        "==== OUTPUT SCHEMA — return ONLY this JSON, no prose ====\n"
        '{"summary": "...", '
        '"skills": [{"group": "Languages", "items": ["Python", ...]}, ...], '
        '"experience": [{"company": "...", "role": "...", "location": "...", '
        '"dates": "...", "bullets": ["...", "...", "...", "..."]}], '
        '"projects": [{"name": "...", "tech": "...", "link": "...", "bullets": [...]}], '
        '"education": [{"school": "...", "degree": "...", "location": "...", '
        '"dates": "...", "gpa": "...", "coursework": "..."}], '
        '"ats_keywords": ["Python", "PyTorch", "AWS", ...]}\n'
        "Skills MUST be an array of objects, NOT a dict. "
        "ats_keywords MUST be a flat array of the top 12 hard-skill keywords "
        "(languages, frameworks, cloud, tools) extracted from the JD. No soft skills."
    )

    awards_txt = "".join(
        f"  - {a.get('name','')} ({a.get('date','')}): {a.get('description','')}\n"
        for a in (master.get("awards") or []) if isinstance(a, dict)
    )
    activities_txt = "\n".join(f"  - {a}" for a in (master.get("activities") or []))
    certs_txt = "\n".join(f"  - {cert}" for cert in (master.get("certifications") or []))
    extras_block = ""
    if awards_txt:
        extras_block += f"AWARDS:\n{awards_txt}"
    if activities_txt:
        extras_block += f"ACTIVITIES:\n{activities_txt}\n"
    if certs_txt:
        extras_block += f"CERTIFICATIONS:\n{certs_txt}\n"

    narrative_block = ""
    if stories:
        narrative_block = "\nNARRATIVE CONTEXT — when a bullet maps to one of these, use its exact metric/outcome:\n"
        for s in stories[:2]:
            narrative_block += (
                f"  Story: {s.get('title','')}\n"
                f"  One-liner: {s.get('one_liner','')}\n"
                f"  Tags: {', '.join(s.get('tags', []))}\n\n"
            )

    guidelines_block = ""
    if guidelines:
        guidelines_block = "\nRESUME WRITING GUIDELINES — apply as quality gates:\n"
        for g in guidelines[:3]:
            chunk = (g.get("body") or "").strip()[:450]
            if chunk:
                guidelines_block += f"{chunk}\n\n"

    # Keep the MASTER block byte-identical across every job so providers with
    # automatic prefix caching (DeepSeek/Mistral/Gemini) serve the ~14 KB master
    # from cache on jobs 2..N of a run instead of re-billing it each time. That
    # means NOT mutating master (its projects must stay in canonical order). To
    # keep the old "stop defaulting to the same flashy projects" behaviour, the
    # per-JD relevance ranking is emitted as an explicit priority hint placed
    # AFTER the job description (in the volatile tail), not baked into the block.
    jd_for_rank = f"{_safe_title(job)} {_safe_desc(job, 3500)}"
    ranked_projects = _rank_projects_by_jd(master.get("projects") or [], jd_for_rank)
    ranked_names = [str(p.get("name", "")).strip() for p in ranked_projects if p.get("name")]
    project_priority_hint = (
        "PROJECT PRIORITY FOR THIS ROLE (most relevant first):\n"
        f"  {', '.join(ranked_names)}\n"
        if ranked_names else ""
    )

    user_prompt = (
        f"MASTER RESUME:\n{json.dumps(master, indent=2)}\n\n"
        f"{extras_block}"
        f"{narrative_block}"
        f"{guidelines_block}"
        f"JOB DESCRIPTION:\n"
        f"Company: {_safe_company(job)}\n"
        f"Title: {_safe_title(job)}\n"
        f"Location: {job.get('location','')}\n\n"
        f"{_safe_desc(job, 3500)}\n\n"
        f"{project_priority_hint}\n"
        "Produce the tailored resume JSON. Use the upper end of every budget. "
        "Never use em dashes (use commas or semicolons instead). "
        "Ensure at least 25 skills total."
    )

    from .schemas import RESUME_SCHEMA
    tailored = provider.json_call(
        system, user_prompt, max_tokens=6000, schema=RESUME_SCHEMA,
    )
    ats_kws = tailored.pop("ats_keywords", []) if isinstance(tailored, dict) else []
    tailored = _apply_guarantees(tailored, master, fallback={})
    LOG.info(
        "tailor: done for %s / %s | stories=%d guidelines=%d",
        _safe_company(job), _safe_title(job), len(stories), len(guidelines),
    )
    state["tailored_json"] = tailored
    state["ats_keywords"] = [str(k).strip() for k in ats_kws if k] if isinstance(ats_kws, list) else []


def _extract_audit_from_tailor_output(state: dict) -> None:
    """Compute ATS keyword coverage using keywords extracted during the tailor step.

    No LLM call — uses the ats_keywords field the tailor already emitted, then
    checks coverage against the tailored resume JSON with pure Python string search.
    """
    jd_keywords = state.get("ats_keywords") or []
    tailored = state["tailored_json"]

    if not jd_keywords:
        state["audit"] = {"jd_keywords": [], "missing_keywords": [], "coverage_pct": 100.0, "passed": True}
        return

    resume_text = json.dumps(tailored).lower()
    missing = [kw for kw in jd_keywords if kw.lower() not in resume_text]
    coverage_pct = round((1 - len(missing) / len(jd_keywords)) * 100, 1)
    passed = coverage_pct >= KEYWORD_COVERAGE_THRESHOLD * 100

    LOG.info(
        "keyword_audit: %.0f%% coverage (%d/%d) -- %s%s",
        coverage_pct,
        len(jd_keywords) - len(missing),
        len(jd_keywords),
        "PASS" if passed else "FAIL",
        f" -- missing: {missing}" if not passed else "",
    )

    state["audit"] = {
        "jd_keywords": jd_keywords,
        "missing_keywords": missing,
        "coverage_pct": coverage_pct,
        "passed": passed,
    }


def _run_keyword_fix(state: dict, provider: LLMProvider) -> None:
    master = state["master_resume"]
    job = state["job"]
    tailored = state["tailored_json"]
    missing = state["audit"].get("missing_keywords", [])

    LOG.info("keyword_fix: patching %d missing keywords: %s", len(missing), missing)

    system = (
        "You are a resume editor improving ATS keyword coverage. "
        "Add each missing keyword ONLY if the candidate has truthful experience with it.\n"
        "Priority: skills section first, then bullets, then summary as last resort.\n"
        f"Do NOT change metrics, dates, company names. Preserve bullet line-fill: "
        f"if a bullet is a single line ({_lf.SINGLE_TARGET}-{_lf.SINGLE_MAX} chars), "
        f"keep it in that band; if it's a double line ({_lf.DOUBLE_MIN}-{_lf.DOUBLE_MAX}), "
        f"keep it there. Never push a bullet into the {_lf.FORBIDDEN_LO}-{_lf.FORBIDDEN_HI} "
        f"forbidden zone. "
        "Return ONLY valid JSON."
    )

    try:
        user_prompt = (
            f"MASTER RESUME:\n{json.dumps(master, indent=2)}\n\n"
            f"JOB: {_safe_company(job)} -- {_safe_title(job)}\n\n"
            f"CURRENT RESUME JSON:\n{json.dumps(tailored, indent=2)}\n\n"
            f"MISSING KEYWORDS TO ADD WHERE TRUTHFUL:\n{json.dumps(missing)}\n\n"
            "Return the updated resume JSON."
        )
        from .schemas import RESUME_SCHEMA
        fixed = provider.json_call(
            system, user_prompt, max_tokens=4096, schema=RESUME_SCHEMA,
        )
        fixed = _apply_guarantees(fixed, master, fallback=tailored)
        LOG.info("keyword_fix: done")
        state["tailored_json"] = fixed
    except Exception as e:
        LOG.warning("keyword_fix failed (%s) -- keeping current resume", e)

    state["keyword_fixed"] = True


def _run_critique(state: dict, provider: LLMProvider) -> None:
    job = state["job"]
    tailored = state["tailored_json"]
    rev = state.get("revision_count", 0)

    profile = state.get("profile") or derive_profile(state["master_resume"])
    titles = profile.get("identity_titles") or ["professional"]
    real_titles_str = " or ".join(f"'{t.lower()}'" for t in titles)
    if profile.get("seniority", "professional") == "professional":
        early_career_flag = (
            " or calls the candidate an 'intern'/'new grad' (they are an "
            "experienced professional)"
        )
    else:
        early_career_flag = ""

    system = (
        "You are a senior technical recruiter doing a final quality check. "
        "Identify the 1-3 most impactful improvements only.\n\n"
        "Check in priority order:\n"
        "  1. IDENTITY: the summary's opening identity NOUN must be the candidate's "
        f"     REAL title — {real_titles_str} (optionally with a JD-relevant focus "
        "     adjective). FLAG it if the opening parrots the JD's job title (e.g. "
        f"     'Product Marketing Engineer', 'Solutions Engineer'){early_career_flag}.\n"
        f"  2. WEAK BULLETS: any bullet generic, missing a metric when master "
        f"     content clearly supports one, under-filling its line, OR landing in "
        f"     the forbidden {_lf.FORBIDDEN_LO}-{_lf.FORBIDDEN_HI} char range (must "
        f"     be {_lf.SINGLE_TARGET}-{_lf.SINGLE_MAX} OR {_lf.DOUBLE_MIN}-{_lf.DOUBLE_MAX} "
        f"     to fully fill its lines)?\n"
        "  3. WRONG PROJECTS: would a different project fit JD domain better?\n"
        "  4. REPEATED VERBS: same action verb used twice in one role?\n"
        "  5. SPARSE SKILLS: fewer than 20 skills total?\n\n"
        'Return JSON: {"issues": ["..."], "severity": "none"|"minor"|"medium"|"major", "passed": true|false}\n'
        'passed=true when severity is "none" or "minor". '
        "Flag only issues that would meaningfully improve the application."
    )

    try:
        # Surface the same matched guidelines that drove tailoring so the
        # critique evaluates against the same rubric. Top 2 are enough —
        # critique is a small JSON call and we don't want to bloat it.
        guidelines = state.get("guidelines") or []
        guidelines_block = ""
        if guidelines:
            guidelines_block = "\nRUBRIC EXTRACTS (use as your scoring criteria):\n"
            for g in guidelines[:2]:
                chunk = (g.get("body") or "").strip()[:400]
                if chunk:
                    guidelines_block += f"{chunk}\n\n"

        user_prompt = (
            f"JOB: {_safe_company(job)} -- {_safe_title(job)} (rev {rev})\n\n"
            f"{_safe_desc(job, 2500)}\n\n"
            f"{guidelines_block}"
            f"TAILORED RESUME:\n{json.dumps(tailored, indent=2)}"
        )
        from .schemas import CRITIQUE_SCHEMA
        critique = provider.json_call(
            system, user_prompt, max_tokens=500, schema=CRITIQUE_SCHEMA,
        )
        if not isinstance(critique, dict):
            critique = {"issues": [], "severity": "none", "passed": True}
        if "passed" not in critique:
            critique["passed"] = critique.get("severity", "none") in ("none", "minor")
    except Exception as e:
        LOG.warning("critique failed (%s) -- treating as passed", e)
        critique = {"issues": [], "severity": "none", "passed": True}

    LOG.info(
        "critique (rev %d): severity=%s, %d issue(s) -- %s",
        rev,
        critique.get("severity", "?"),
        len(critique.get("issues", [])),
        "PASS" if critique.get("passed") else "REVISE",
    )

    state["critique"] = critique


def _run_revise(state: dict, provider: LLMProvider) -> None:
    master = state["master_resume"]
    job = state["job"]
    tailored = state["tailored_json"]
    issues = state["critique"].get("issues", [])
    rev = state.get("revision_count", 0)

    LOG.info("revise: applying %d fix(es) (revision %d -> %d)", len(issues), rev, rev + 1)

    system = (
        "You are a resume editor making targeted, surgical improvements. "
        "Apply ONLY the listed fixes. Do NOT fabricate content not in MASTER. "
        "Return ONLY valid JSON.\n\n"
        f"A printed line holds ~{_lf.LINE_CHARS} chars. Every bullet must FILL its "
        f"line(s): EITHER {_lf.SINGLE_TARGET}-{_lf.SINGLE_MAX} chars (a full single "
        f"line) OR {_lf.DOUBLE_MIN}-{_lf.DOUBLE_MAX} chars (full two lines). "
        f"{_lf.FORBIDDEN_LO}-{_lf.FORBIDDEN_HI} chars is FORBIDDEN (orphan wrap), and "
        f"under {_lf.SINGLE_TARGET} under-fills the single line.\n\n"
        "Fix guidance:\n"
        "  Identity mismatch -> rewrite only the summary's opening clause\n"
        f"  Weak bullet (forbidden zone) -> extend with concrete detail to reach "
        f"    {_lf.DOUBLE_MIN}-{_lf.DOUBLE_MAX} chars, OR tighten to "
        f"    {_lf.SINGLE_TARGET}-{_lf.SINGLE_MAX} chars\n"
        f"  Under-filled single -> add concrete detail from master to reach "
        f"    {_lf.SINGLE_TARGET}-{_lf.SINGLE_MAX} chars\n"
        f"  Weak bullet (generic) -> expand with PAR format (context -> action -> "
        f"    result/metric) into {_lf.DOUBLE_MIN}-{_lf.DOUBLE_MAX} chars\n"
        "  Wrong project -> swap weakest-fit project for better-fit one from master\n"
        "  Repeated verb -> replace duplicate with a different strong action verb\n"
        "  Sparse skills -> add items from master skill groups until >= 25 total"
    )

    try:
        # Carry guidelines through so the revise step applies the same rubric
        # as critique — useful when critique flagged a guideline violation.
        guidelines = state.get("guidelines") or []
        guidelines_block = ""
        if guidelines:
            guidelines_block = "\nGUIDELINES TO RESPECT WHEN REVISING:\n"
            for g in guidelines[:2]:
                chunk = (g.get("body") or "").strip()[:400]
                if chunk:
                    guidelines_block += f"{chunk}\n\n"

        issues_block = "\n".join(f"  {i + 1}. {issue}" for i, issue in enumerate(issues))
        user_prompt = (
            f"MASTER RESUME:\n{json.dumps(master, indent=2)}\n\n"
            f"JOB: {_safe_company(job)} -- {_safe_title(job)}\n\n"
            f"{_safe_desc(job, 2000)}\n\n"
            f"{guidelines_block}"
            f"CURRENT RESUME JSON:\n{json.dumps(tailored, indent=2)}\n\n"
            f"FIXES TO APPLY:\n{issues_block}\n\n"
            "Return the corrected resume JSON."
        )
        from .schemas import RESUME_SCHEMA
        revised = provider.json_call(
            system, user_prompt, max_tokens=4096, schema=RESUME_SCHEMA,
        )
        revised = _apply_guarantees(revised, master, fallback=tailored)
        LOG.info("revise: revision %d complete", rev + 1)
        state["tailored_json"] = revised
    except Exception as e:
        LOG.warning("revise failed (%s) -- keeping current resume", e)

    state["revision_count"] = rev + 1


# ---------------------------------------------------------------------------
# Pipeline runner (plain Python — no LangGraph)
# ---------------------------------------------------------------------------

def _step_with_chain(chain: list[LLMProvider], fn, *, any_error: bool, label: str) -> bool:
    """Try fn(provider) against each provider in chain. Returns True on first success.

    any_error=True  — retry on any exception (used for tailor: JSON parse failures
                      are as likely as quota errors on free-tier models).
    any_error=False — retry only on quota/rate-limit signals (cheaper steps).
    """
    for provider in chain:
        try:
            fn(provider)
            return True
        except Exception as e:
            if any_error or is_quota_error(e):
                LOG.warning("%s failed on '%s' (%s) -- trying next provider",
                            label, provider.name, str(e)[:120])
                continue
            LOG.warning("%s failed on '%s' (%s) -- skipping step",
                        label, provider.name, str(e)[:120])
            return False
    return False


def run_tailor_graph(
    master_resume: dict,
    job: dict,
    tailor_chain: list[LLMProvider],
    critique_chain: list[LLMProvider],
    stories: list | None = None,
    guidelines: list | None = None,
    metrics_sink: dict | None = None,
    relinefit_chain: list[LLMProvider] | None = None,
) -> dict:
    """Self-correcting resume tailoring pipeline.

    Drop-in replacement for Tailor.tailor_resume(). Returns the structured
    JSON dict that build_resume_onepage() expects.

    tailor_chain:   Providers to use for tailor / keyword_fix / revise steps.
    critique_chain: Providers to use for the critique step (can be cheaper models).
    relinefit_chain: Providers for the Tier-2 line-fit rescue. Wants a strong
        model but thinking OFF (a bounded mechanical rewrite where CoT eats the
        budget and returns empty). Defaults to tailor_chain when not supplied.

    Each step is attempted against its chain from index 0 on every call — there
    is no persistent state between jobs, so a provider that failed on one job is
    still tried first for the next.
    """
    state = _make_state(master_resume, job, stories or [], guidelines or [])

    # Step 1: tailor (required). Retry on ANY exception because free-tier models
    # often return malformed JSON rather than an HTTP error.
    tailor_ok = _step_with_chain(
        tailor_chain,
        lambda p: _run_tailor(state, p),
        any_error=True,
        label="tailor",
    )

    if not tailor_ok or not state.get("tailored_json"):
        LOG.error("tailor step exhausted all providers — returning master as-is")
        return _apply_guarantees(master_resume, master_resume, fallback=master_resume)
    _log_bullet_bands(state, "tailor")

    # Step 2: keyword audit — zero LLM calls; ats_keywords came from the tailor output
    _extract_audit_from_tailor_output(state)

    # Step 3: keyword fix (conditional on audit failure)
    if not state["audit"].get("passed", True):
        if _step_with_chain(
            tailor_chain,
            lambda p: _run_keyword_fix(state, p),
            any_error=False,
            label="keyword_fix",
        ):
            _log_bullet_bands(state, "keyword_fix")

    # Step 4: critique + revise loop (optional — failure is non-fatal)
    for _ in range(MAX_REVISIONS + 1):
        crit_ok = _step_with_chain(
            critique_chain,
            lambda p: _run_critique(state, p),
            any_error=False,
            label="critique",
        )
        if not crit_ok:
            break

        if state["critique"].get("passed", True):
            break
        if state.get("revision_count", 0) >= MAX_REVISIONS:
            break

        rev_ok = _step_with_chain(
            tailor_chain,
            lambda p: _run_revise(state, p),
            any_error=False,
            label="revise",
        )
        if not rev_ok:
            break
        _log_bullet_bands(state, "revise")

    # Step 5: line-fit pass — two-tier strategy.
    #
    # Tier 1 (deterministic, no LLM): line_fitter swaps forbidden-zone bullets
    # for matching `bullets_all` variants from master, or trims them via
    # regex-priority rules. Handles 70-95% of cases.
    #
    # Tier 2 (LLM rescue, only for stragglers): if line_fitter couldn't
    # resolve some bullets, escalate to an LLM call. Routed through the
    # relinefit_chain (strong model, e.g. deepseek, but thinking OFF), NOT the
    # critique_chain: rewriting a long bullet down to a dense single line is a
    # hard generation task — the weaker critique model (mistral) does it
    # unreliably — yet CoT only wastes budget on this bounded mechanical rewrite.
    # Falls back to tailor_chain when no dedicated chain was supplied.
    # Skipped entirely when nothing was flagged.
    if state.get("tailored_json"):
        fitted, fit_stats = fit_bullets_to_bands(
            state["tailored_json"], state["master_resume"],
        )
        state["tailored_json"] = _apply_guarantees(
            fitted, state["master_resume"], fallback=state["tailored_json"],
        )
        state["line_fit_stats"] = fit_stats
        _log_bullet_bands(state, "line_fitter")
        if fit_stats.get("flagged_for_llm"):
            if _step_with_chain(
                relinefit_chain or tailor_chain,
                lambda p: _run_relinefit_rescue(state, p),
                any_error=True,
                label="relinefit_rescue",
            ):
                _log_bullet_bands(state, "relinefit_rescue")

    # Finalize metrics — duration + final band counts.
    import time as _time
    metrics = state.setdefault("metrics", {})
    metrics["total_seconds"] = round(_time.time() - metrics.get("started_at", _time.time()), 2)
    final_steps = metrics.get("steps") or []
    if final_steps:
        metrics["final_band_counts"] = final_steps[-1]["bullets"]
        metrics["final_forbidden_count"] = final_steps[-1]["bullets"].get("forbidden", 0)
    state["metrics"] = metrics
    if metrics_sink is not None:
        metrics_sink.update(metrics)

    return state.get("tailored_json") or _apply_guarantees(master_resume, master_resume, fallback=master_resume)


# ---------------------------------------------------------------------------
# Line-fit pass — rewrite bullets stuck in the wrap-waste zone
# ---------------------------------------------------------------------------

def _collect_forbidden_bullets(tailored: dict) -> list[dict]:
    """Return [{section, item_idx, bullet_idx, length, text}] for every bullet
    whose length is in the forbidden wrap-waste zone."""
    out: list[dict] = []
    for section in ("experience", "projects"):
        entries = tailored.get(section) or []
        for i, entry in enumerate(entries):
            bullets = entry.get("bullets") or []
            for j, b in enumerate(bullets):
                if not isinstance(b, str):
                    continue
                n = len(b)
                if _lf.FORBIDDEN_LO <= n <= _lf.FORBIDDEN_HI:
                    out.append({
                        "section": section,
                        "item_idx": i,
                        "bullet_idx": j,
                        "length": n,
                        "text": b,
                    })
    return out


def _master_bullets_for_role(master: dict, section: str, role: str, company: str) -> list[str]:
    """Pull the full bullet pool from master for context — lets the LLM draw on
    real metrics/details when extending rather than fabricating."""
    if section == "experience":
        for e in master.get("experience", []) or []:
            head = (e.get("role", "") or "").lower().split("(")[0].strip()
            co = (e.get("company", "") or "").lower()
            if co == (company or "").lower() and (head in role.lower() or role.lower().startswith(head[:18])):
                return list(e.get("bullets_all") or e.get("bullets") or [])
    if section == "projects":
        for p in master.get("projects", []) or []:
            if (p.get("name", "") or "").lower() == (role or "").lower():
                return list(p.get("bullets_all") or p.get("bullets") or [])
    return []


# Deterministic line_fitter already tried master substitution + regex trim.
# Anything that reaches the LLM rescue is genuinely hard. Each pass re-prompts
# (with escalating emphasis) only the bullets still out of band, so a few cheap
# passes meaningfully lift the hit rate on the hardest bullets without burning
# calls on ones already fixed.
_RELINEFIT_MAX_PASSES = 3


def _is_band_ok(n: int) -> bool:
    """Renders cleanly (single OR double band). Used to decide what needs rescue."""
    return n <= _lf.SINGLE_MAX or (_lf.DOUBLE_MIN <= n <= _lf.DOUBLE_MAX + _lf.DOUBLE_OK_OVERSHOOT)


def _rescue_accept(n: int) -> bool:
    """Stricter than _is_band_ok: a rescue rewrite is only accepted if it FILLS
    a single line (>= SINGLE_TARGET) or lands in the double band. This rejects
    rewrites that come back under-filled (retry) or in the forbidden zone (no
    regression) — a rejected bullet falls back to its original clean line."""
    return (_lf.SINGLE_TARGET <= n <= _lf.SINGLE_MAX
            or _lf.DOUBLE_MIN <= n <= _lf.DOUBLE_MAX + _lf.DOUBLE_OK_OVERSHOOT)


def _relinefit_pass(offenders: list[dict], tailored: dict, master: dict,
                    provider: LLMProvider, attempt: int,
                    mode: str = "compress") -> dict[int, str]:
    """Make one LLM rewrite pass over a homogeneous group of offenders.

    `mode` is "compress" (bullets too long -> trim to one full line) or "extend"
    (clean single but under-filled -> add real master detail). Each mode gets a
    single-minded prompt; mixing both in one call makes the model pick a single
    global direction. Returns {offender_idx: new_text} for accepted rewrites.
    Raises on provider failure so the chain can fall over."""
    # Build context block: each offender plus the master bullet pool for that role.
    context_lines = []
    for k, off in enumerate(offenders):
        section_entries = tailored.get(off["section"]) or []
        entry = section_entries[off["item_idx"]] if off["item_idx"] < len(section_entries) else {}
        if off["section"] == "experience":
            label = f"{entry.get('role','')} @ {entry.get('company','')}"
            master_pool = _master_bullets_for_role(
                master, "experience", entry.get("role", ""), entry.get("company", ""),
            )
        else:
            label = entry.get("name", "")
            master_pool = _master_bullets_for_role(master, "projects", entry.get("name", ""), "")
        pool_block = ""
        if master_pool:
            pool_block = "  MASTER POOL (draw extra detail/metrics from here, do not fabricate):\n"
            for mb in master_pool[:8]:
                pool_block += f"    - {mb}\n"
        context_lines.append(
            f"[{k}] section={off['section']} item=\"{label}\" current_len={off['length']}\n"
            f"  CURRENT: {off['text']}\n"
            f"{pool_block}"
        )

    line_chars = _lf.LINE_CHARS
    single_target, single_max = _lf.SINGLE_TARGET, _lf.SINGLE_MAX
    target_range = f"{single_target}-{single_max} chars"

    if mode == "extend":
        # Bullets that already fit one line but leave it under-filled. The ONLY
        # job is to lengthen them with real master detail to a full line.
        good = (
            f"  TOO SHORT ({single_target - 28} chars): \"Built RAG chatbot for "
            f"incident diagnosis.\"\n"
            f"  GOOD ({single_max - 3} chars, full line): \"Built RAG chatbot on "
            f"Azure AI Search indexing 50K+ team emails for automated incident "
            f"diagnosis and resolution.\""
        )
        emphasis = "" if attempt == 0 else (
            "PREVIOUS ATTEMPT WAS STILL TOO SHORT. Add more concrete detail. "
        )
        system = (
            f"You lengthen resume bullets that are too short — they sit on one "
            f"printed line (~{line_chars} chars wide) but leave the right side "
            f"empty, which looks sparse.\n\n"
            f"{emphasis}Rewrite EACH bullet to {target_range} (a full single line) "
            f"by ADDING concrete, truthful detail from its MASTER POOL: scope "
            f"(team size, volume), a specific technology, or a real metric. NEVER "
            f"invent facts not in the bullet or its master pool. NEVER exceed "
            f"{single_max} chars (that wraps to a second line). Keep the original "
            f"verb and meaning. No em dashes (use ' - ').\n\n"
            f"Count characters: land {target_range}; never over {single_max}.\n\n"
            f"EXAMPLE (count each char):\n{good}\n\n"
            f"Return ONLY a JSON object: {{\"rewrites\": [{{\"idx\": <int>, "
            f"\"text\": \"...\"}}]}}. Idx matches the [k] tag. Include EVERY bullet."
        )
        user_prompt = (
            f"Bullets to lengthen ({len(offenders)} total). Each MUST reach "
            f"{target_range} (never over {single_max}). Count chars:\n\n"
            + "\n".join(context_lines)
        )
    else:
        # COMPRESS: bullets too long (wrap to a near-empty 2nd line, or 3 lines).
        # Empirically the model lands ~5-13 chars ABOVE whatever max we state, so
        # we state a range whose top sits BELOW the true ceiling (single_max) to
        # absorb that overshoot. A narrow explicit range ("110-125") anchors the
        # model far better than "<= max"; and "cut a whole clause" is what gets a
        # ~180-char bullet down onto one line.
        stated_lo = max(60, single_target - 6)
        stated_hi = single_max - 5
        stated_range = f"{stated_lo}-{stated_hi} characters"
        good = (
            f"  GOOD ({stated_hi - 2} chars, one packed line): \"Architected RAG "
            f"chatbot on Azure AI Search indexing 50K+ team emails for automated "
            f"incident triage and resolution.\"\n"
            f"  BAD (too long, wraps to a near-empty 2nd line): \"Architected RAG "
            f"chatbot indexing 50K+ team emails via Azure AI Search, delivering "
            f"automated incident diagnosis and step-by-step resolutions for "
            f"on-call engineers across the org.\""
        )
        emphasis = "" if attempt == 0 else (
            "PREVIOUS ATTEMPT WAS STILL TOO LONG. Drop an entire secondary clause "
            "this time - keep only the single strongest action and its metric. "
        )
        system = (
            f"You shorten resume bullets that are too long — they wrap onto a "
            f"second line that stays mostly empty, wasting space. A printed line "
            f"holds about {line_chars} chars, so each bullet must fit on ONE line.\n\n"
            f"{emphasis}Rewrite EACH bullet to STRICTLY {stated_range}. To get "
            f"there you MUST cut a whole secondary clause (and any filler, "
            f"qualifiers, or parentheticals) — do not just shave a word or two. "
            f"Keep the single strongest action verb and the single strongest "
            f"metric; do NOT weaken verbs or drop JD-relevant technologies. "
            f"Shorter (down to {stated_lo}) is better than going over. No em "
            f"dashes (use ' - ').\n\n"
            f"Count characters as you write — the target is {stated_range}.\n\n"
            f"EXAMPLE (count each char):\n{good}\n\n"
            f"Return ONLY a JSON object: {{\"rewrites\": [{{\"idx\": <int>, "
            f"\"text\": \"...\"}}]}}. Idx matches the [k] tag. Include EVERY bullet."
        )
        user_prompt = (
            f"Bullets to shorten ({len(offenders)} total). Each MUST end up "
            f"{stated_range} (cut a whole clause). Count chars:\n\n"
            + "\n".join(context_lines)
        )

    # Re-raise so _step_with_chain can fall through to the next provider when
    # the current one returns empty/malformed.
    from .schemas import RELINEFIT_SCHEMA
    resp = provider.json_call(
        system, user_prompt, max_tokens=2200, schema=RELINEFIT_SCHEMA,
    )
    rewrites = resp.get("rewrites") if isinstance(resp, dict) else None
    if not isinstance(rewrites, list):
        raise RuntimeError("relinefit: provider returned no 'rewrites' array")

    accepted: dict[int, str] = {}
    for rw in rewrites:
        if not isinstance(rw, dict):
            continue
        idx = rw.get("idx")
        new_text = rw.get("text")
        if not isinstance(idx, int) or not isinstance(new_text, str):
            continue
        if idx < 0 or idx >= len(offenders):
            continue
        new_text = new_text.strip()
        # Mode-aware acceptance:
        #  - extend: only accept a FILLED single (>= SINGLE_TARGET) or a double;
        #    a barely-longer bullet wasn't worth the rewrite.
        #  - compress: accept any clean band. Escaping the forbidden/overlong
        #    zone is the priority; reverting to the original orphan-wrap because
        #    the model landed at 110 instead of 118 would be strictly worse.
        n = len(new_text)
        ok = _rescue_accept(n) if mode == "extend" else _is_band_ok(n)
        if ok:
            accepted[idx] = new_text
    return accepted


def _has_master_pool(master: dict, section: str, entry: dict) -> bool:
    if section == "experience":
        return bool(_master_bullets_for_role(
            master, "experience", entry.get("role", ""), entry.get("company", "")))
    return bool(_master_bullets_for_role(master, "projects", entry.get("name", ""), ""))


def _collect_bullets(tailored: dict, master: dict, predicate, mode: str) -> list[dict]:
    """Scan current experience+project bullets, returning offender dicts for
    bullets matching `predicate(length, has_master_pool)`."""
    out: list[dict] = []
    for section in ("experience", "projects"):
        for i, entry in enumerate(tailored.get(section, []) or []):
            has_pool = _has_master_pool(master, section, entry)
            for j, b in enumerate(entry.get("bullets") or []):
                if isinstance(b, str) and predicate(len(b), has_pool):
                    out.append({"section": section, "item_idx": i, "bullet_idx": j,
                                "length": len(b), "text": b, "mode": mode})
    return out


def _run_relinefit_rescue(state: dict, provider: LLMProvider) -> None:
    """Two-phase LLM rescue for bullets the deterministic line_fitter couldn't
    fix. We re-scan the CURRENT resume (robust to _apply_guarantees edits) rather
    than trusting stale flagged indices.

    Phase 1 COMPRESS: every too-long bullet (forbidden/overlong) -> one clean
    single line. Accepts any clean band, so it never reverts to the original
    orphan-wrap even if the model lands short.

    Phase 2 EXTEND: every under-filled single (INCLUDING ones phase 1 just
    produced) that has real master detail -> filled toward a full line. This is
    what makes the final fill reliable regardless of where compression landed.
    """
    tailored = state.get("tailored_json") or {}
    master = state.get("master_resume") or {}
    applied = 0
    first_call_done = False

    def _run_group(offenders: list[dict], mode: str) -> None:
        nonlocal applied, first_call_done
        pending = list(enumerate(offenders))
        for attempt in range(_RELINEFIT_MAX_PASSES):
            if not pending:
                break
            local = [off for _i, off in pending]
            try:
                accepted = _relinefit_pass(local, tailored, master, provider,
                                           attempt=attempt, mode=mode)
            except Exception:
                # Let the very first call propagate so _step_with_chain can fall
                # over to the next provider; once anything succeeded, keep it.
                if not first_call_done:
                    raise
                LOG.warning("relinefit %s pass %d failed — keeping prior", mode, attempt + 1)
                break
            first_call_done = True
            nextp = []
            for li, (oi, off) in enumerate(pending):
                if li in accepted:
                    tailored[off["section"]][off["item_idx"]]["bullets"][off["bullet_idx"]] = accepted[li]
                    applied += 1
                else:
                    nextp.append((oi, off))
            LOG.info("relinefit %s pass %d: accepted %d, retrying %d",
                     mode, attempt + 1, len(accepted), len(nextp))
            pending = nextp

    # Phase 1 — compress too-long bullets onto one clean line.
    compress = _collect_bullets(tailored, master, lambda n, pool: not _is_band_ok(n), "compress")
    if compress:
        LOG.info("relinefit_rescue: %d bullet(s) to compress", len(compress))
        _run_group(compress, "compress")

    # Phase 2 — fill under-filled singles (re-scanned, so it catches anything
    # phase 1 over-trimmed). Only bullets with master detail to draw on.
    extend = _collect_bullets(
        tailored, master,
        lambda n, pool: pool and _lf.is_underfilled_single(n), "extend")
    if extend:
        LOG.info("relinefit_rescue: %d under-filled single(s) to extend", len(extend))
        _run_group(extend, "extend")

    if applied:
        # Re-assert downstream invariants (skill dedup, project/experience dedup)
        # after the surgical edits.
        state["tailored_json"] = _apply_guarantees(tailored, master, fallback=tailored)

    LOG.info("relinefit_rescue: applied %d rewrite(s)", applied)
