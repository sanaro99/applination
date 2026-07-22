"""
Candidate identity profile — derived from the master resume.

The tailoring engine used to hardcode one person's identity ("Software
Engineer / SRE at UBS, MS at UW, 4+ years professional") into prompts and
deterministic post-processors. That made truthful output impossible for any
other user. This module derives the same facts from ``resume.yaml`` instead,
so the engine works for anyone.

Everything is derived from the master resume's ``experience``/``education``.
A user (or the onboarding flow) may override any field via an optional
top-level ``profile:`` block in ``resume.yaml``:

    profile:
      identity_titles: ["Software Engineer", "SRE"]  # canonical real titles
      seniority: "professional"                       # student | new-grad | professional
      preserve_fulltime: true                          # keep non-internship roles in tailored output
      education_close: "MS, University of Washington"  # closing credential line

The derived ``profile`` dict is threaded through the deterministic guards in
``tailor.py`` and the tailoring prompt in ``tailor_graph.py``.
"""
from __future__ import annotations
import re

# Strip leading seniority qualifiers so "Sr. Software Engineer" and
# "Software Engineer" collapse to the same canonical identity title.
_SENIORITY_PREFIX = re.compile(
    r"^(sr\.?|senior|jr\.?|junior|lead|principal|staff|associate)\s+", re.IGNORECASE
)
# Strip trailing internship qualifiers so a student's "SWE Intern" / "Data
# Science Intern" collapses to the underlying identity ("SWE" / "Data Science").
_TRAILING_QUALIFIER = re.compile(
    r"\s*\b(intern(ship)?|co-?op|trainee|apprentice)\b\s*$", re.IGNORECASE
)


# Title tokens marking a role as senior / staff / leadership — above the
# early-career band this pipeline targets (internships, new-grad, early FT).
# "Lead"/"architect" are only treated as senior when qualifying an engineering
# or product role, so "Lead Generation Specialist" isn't caught.
_OVER_SENIOR_RE = re.compile(
    r"\b("
    r"staff|principal|distinguished|fellow|director|"
    r"vice\s+president|vp|head\s+of|(senior|sr\.?)\s+manager|"
    r"(software|engineering|technical|tech|product|data|design|platform)\s+lead|"
    r"lead\s+(software|engineer|engineering|developer|data|ml|product|design|"
    r"architect|scientist|backend|frontend|platform|infrastructure|devops|sre)|"
    r"architect"
    r")\b",
    re.IGNORECASE,
)
# Plain "Senior" individual-contributor titles — too senior only for the
# earliest-career candidates (students / new-grads), fine for a professional.
_SENIOR_IC_RE = re.compile(r"\b(senior|sr\.?)\b", re.IGNORECASE)


def role_is_above_level(title: str, profile: dict | None) -> bool:
    """True if a job title is clearly too senior for this candidate.

    Deterministic guardrail for the ranking stage: LLM scorers over-weight
    skill overlap and let Staff/Principal/Director/Lead roles through for an
    early-career candidate (e.g. a "Staff Product Manager" for a student).
    Staff+/leadership/executive titles are dropped for everyone this tool
    serves; plain "Senior" IC titles are dropped only for students and
    new-grads. Honors an explicit ``profile.seniority`` override.
    """
    title = title or ""
    if _OVER_SENIOR_RE.search(title):
        return True
    if (profile or {}).get("seniority", "professional") in ("student", "new-grad"):
        return bool(_SENIOR_IC_RE.search(title))
    return False


def _base_title(role: str) -> str:
    role = (role or "").strip()
    prev = None
    while prev != role:
        prev = role
        role = _SENIORITY_PREFIX.sub("", role).strip()
        role = _TRAILING_QUALIFIER.sub("", role).strip()
    return role


def _is_internship(role: str) -> bool:
    return "intern" in (role or "").lower()


def derive_profile(master: dict | None) -> dict:
    """Build the candidate identity profile from the master resume.

    Returns a dict with keys: ``identity_titles`` (list[str]),
    ``primary_title`` (str), ``identity_tokens`` (set[str], lowercase words
    that make up the real titles), ``seniority`` (str), ``preserve_fulltime``
    (bool), ``education_close`` (str).
    """
    master = master or {}
    override = master.get("profile") or {}
    experience = master.get("experience") or []
    fulltime = [
        e for e in experience
        if isinstance(e, dict) and not _is_internship(e.get("role", ""))
    ]

    # --- identity titles ---------------------------------------------------
    titles = override.get("identity_titles")
    if not titles:
        seen: list[str] = []
        for e in fulltime:
            t = _base_title(e.get("role", ""))
            if t and t.lower() not in {s.lower() for s in seen}:
                seen.append(t)
        titles = seen[:3]
    if not titles:
        # No full-time roles (e.g. a student): fall back to any role title.
        for e in experience:
            if isinstance(e, dict):
                t = _base_title(e.get("role", ""))
                if t:
                    titles = [t]
                    break
    titles = [str(t) for t in (titles or ["professional"]) if str(t).strip()]

    # --- seniority ---------------------------------------------------------
    seniority = override.get("seniority")
    if not seniority:
        if fulltime:
            seniority = "professional"
        elif experience:
            seniority = "new-grad"
        else:
            seniority = "student"

    # --- preserve full-time roles -----------------------------------------
    preserve_fulltime = bool(override.get("preserve_fulltime", True))

    # --- closing credential ------------------------------------------------
    education_close = override.get("education_close")
    if education_close is None:
        edu = master.get("education") or []
        if edu and isinstance(edu[0], dict):
            degree = (edu[0].get("degree") or "").strip()
            school = (edu[0].get("school") or "").strip()
            education_close = ", ".join(p for p in (degree, school) if p)
        else:
            education_close = ""

    # --- identity tokens (for the forbidden-noun guard) --------------------
    tokens: set[str] = set()
    for t in titles:
        for w in re.findall(r"[a-z]+", t.lower()):
            if len(w) > 1:
                tokens.add(w)

    return {
        "identity_titles": titles,
        "primary_title": titles[0],
        "identity_tokens": tokens,
        "seniority": seniority,
        "preserve_fulltime": preserve_fulltime,
        "education_close": education_close,
    }


# Skill/experience budgets for the compact resume view below. Kept small so
# prompts that inject it stay inside the ~8K-token ceiling tailor.py works to.
_SUMMARY_SKILL_CAP = 30
_SUMMARY_ROLE_CAP = 3
_SUMMARY_BULLET_CAP = 4


def profile_summary_block(master: dict) -> str:
    """A compact text view of the master resume: summary, skills, recent roles.

    This is the factual spine any free-text generation needs in order to answer
    "what have you worked with?" truthfully. Without it a model is asked to be
    specific with no specifics available, and it invents them — which is why
    this lives here in ``src/`` rather than in one caller: ``tailor.answer_questions``
    and ``server/coach_context`` must ground on the SAME facts, or the Coach and
    the generated application answers will contradict each other.
    """
    parts: list[str] = []

    summaries = master.get("summary_options") or []
    if summaries:
        parts.append(f"Summary: {summaries[0]}")

    core = master.get("core_skills") or []
    skills_groups = master.get("skills") or {}
    flat_skills: list[str] = list(core)
    for group in skills_groups.values():
        if isinstance(group, list):
            flat_skills.extend(group)
    # De-dupe preserving order, cap to keep it readable.
    seen: set[str] = set()
    deduped = [s for s in flat_skills if not (s in seen or seen.add(s))]
    if deduped:
        parts.append("Key skills: " + ", ".join(deduped[:_SUMMARY_SKILL_CAP]))

    experience = master.get("experience") or []
    for role in experience[:_SUMMARY_ROLE_CAP]:
        company = role.get("company", "")
        title = role.get("role", "")
        dates = f"{role.get('start_date', '')}–{role.get('end_date', '')}".strip("–")
        bullets = role.get("bullets_all") or []
        bullet_text = "\n".join(f"  - {b}" for b in bullets[:_SUMMARY_BULLET_CAP])
        parts.append(f"{title} at {company} ({dates}):\n{bullet_text}")

    projects = master.get("projects") or []
    for proj in projects[:2]:
        if not isinstance(proj, dict):
            continue
        pname = proj.get("name", "")
        pbullets = proj.get("bullets_all") or proj.get("bullets") or []
        pb = "\n".join(f"  - {b}" for b in pbullets[:2])
        if pname:
            parts.append(f"Project — {pname}:\n{pb}" if pb else f"Project — {pname}")

    education = master.get("education") or []
    if education:
        ed = education[0]
        parts.append(
            f"Education: {ed.get('degree', '')}, {ed.get('school', '')} "
            f"(GPA {ed.get('gpa', '')})"
        )

    return "\n\n".join(p for p in parts if p)
