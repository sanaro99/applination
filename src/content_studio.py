"""LLM-assisted authoring of master data (stories, bio, resume).

Two operations, both grounded in the candidate's real experience:
  - generate_story(): draft a full story (frontmatter + body) from a plain
    description, returning a structured dict + rendered markdown.
  - tweak_content(): revise an existing story / bio / resume from a freeform
    instruction, returning the new text.

These mirror the instruction->edit pattern in src/tweak.py but operate on the
master-data text formats rather than tailored-resume JSON.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from .master_resume import FORM_KEYS, normalize_skills
from .schemas import STORY_SCHEMA, MASTER_RESUME_SCHEMA, KEYWORDS_SCHEMA

# Frontmatter key order matching the existing story files.
_STORY_KEYS = ("title", "tags", "role_fit", "company_fit", "one_liner")

_GROUNDING = (
    "Ground everything in the candidate's REAL experience described to you. "
    "Never invent employers, projects, technologies, or metrics that were not "
    "provided. No em dashes (use commas or semicolons). No 'passionate', "
    "'thrilled', or 'excited'. Plain, specific, first-person prose."
)


def slugify(title: str) -> str:
    """Filesystem-safe slug for a story filename (no extension)."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return (slug or "story")[:60]


def generate_story(
    description: str,
    *,
    provider,
    taxonomy: str = "",
    existing_titles: list[str] | None = None,
) -> dict:
    """Draft a structured story from a freeform description.

    Returns a dict with keys title, tags, role_fit, company_fit, one_liner,
    body (matching STORY_SCHEMA).
    """
    existing = ", ".join(existing_titles or []) or "(none yet)"
    system = (
        "You write resume 'stories' — short narrative accounts of real work the "
        "candidate has done, used to personalize cover letters and interview "
        "answers. Produce ONE story as a JSON object.\n\n" + _GROUNDING + "\n\n"
        "The body must be 200-320 words with four beats in order: Context (the "
        "problem/setup), What I did (the specific work, name the real tech), "
        "What mattered (the hard or non-obvious part that shows judgment), and "
        "Outcome (a concrete result and what was learned). Write the body as "
        "flowing prose, not labeled sections.\n\n"
        "Pick tags / role_fit / company_fit from this taxonomy where they fit "
        "(add specific ones only when clearly warranted):\n" + (taxonomy or "")
    )
    user = (
        f"Existing story titles (avoid duplicating these): {existing}\n\n"
        f"Describe the story to write:\n{description.strip()}\n\n"
        "Return a JSON object with keys: title, tags (list), role_fit (list), "
        "company_fit (list), one_liner (one sentence hook), body (the prose)."
    )
    data = provider.json_call(system, user, max_tokens=1600, schema=STORY_SCHEMA)
    return _coerce_story(data)


def suggest_keywords(
    description: str, *, provider, existing: list[str] | None = None
) -> list[str]:
    """Suggest job-search keyword/role phrases from a freeform description of
    the roles or kind of work the candidate wants.

    Returns short phrases suitable for job-board query strings (matching the
    style of `search.keywords` in config.yaml), e.g. "backend engineer intern",
    not full sentences. Does not include anything already in `existing`.
    """
    existing_list = ", ".join(existing or []) or "(none yet)"
    system = (
        "You turn a candidate's description of the roles/work they want into "
        "short job-search keyword phrases, the kind typed into a job board's "
        "search box. Each phrase should be 2-5 words, specific enough to filter "
        "listings (e.g. 'backend engineer intern', 'machine learning research', "
        "'data engineer new grad'), not a full sentence and not a single generic "
        "word. Prefer phrases matching how job postings are actually titled."
    )
    user = (
        f"Keywords already in use (do not repeat these): {existing_list}\n\n"
        f"Roles/work the candidate wants:\n{description.strip()}\n\n"
        "Return a JSON object with a 'keywords' array of 2-8 new phrases."
    )
    data = provider.json_call(system, user, max_tokens=400, schema=KEYWORDS_SCHEMA)
    out: list[str] = []
    for k in data.get("keywords") or []:
        s = str(k).strip()
        if s:
            out.append(s)
    return out


def import_resume(text: str, *, provider) -> dict:
    """Extract a structured MASTER resume (the resume.yaml shape) from a raw
    resume — pasted text or text extracted from an uploaded PDF/DOCX.

    Strictly grounded: only content present in the source is used. Returns a
    dict matching MASTER_RESUME_SCHEMA (the caller renders it to YAML and the
    user reviews before saving).
    """
    system = (
        "You convert a raw resume into a structured MASTER resume JSON. Extract "
        "ONLY what is present in the source text — do NOT invent employers, job "
        "titles, dates, metrics, projects, or skills that are not there. "
        + _GROUNDING + "\n\n"
        "Field guidance:\n"
        "- summary_options: 2 truthful 1-2 sentence professional summaries built "
        "from the resume's real content (lead with the candidate's real title).\n"
        "- core_skills: 6-10 load-bearing skills that should appear on every "
        "tailored resume; ats_adjacent_skills: other real skills from the resume.\n"
        "- skills: group all skills into 4-6 named groups (e.g. 'Languages', "
        "'Frameworks & APIs', 'Cloud & DevOps', 'Data & Storage').\n"
        "- experience: each role with company, role (the job title), location, "
        "start_date and end_date as 'Mon YYYY' (or 'Present'), and bullets_all "
        "(the bullet points, lightly cleaned, no em dashes).\n"
        "- projects: any projects with name, tech, link, bullets_all.\n"
        "- education: school, degree, location, start_date, end_date, gpa, "
        "coursework (list).\n"
        "- profile.identity_titles: the candidate's real job title(s), taken from "
        "their most recent NON-internship role (omit internships); if they have "
        "only internships/education, use the field/degree (e.g. 'Software "
        "Engineer'). profile.seniority: 'student' if only education/internships, "
        "'new-grad' if under ~1 year full-time, otherwise 'professional'.\n"
    )
    user = (
        f"RAW RESUME:\n{text.strip()}\n\n"
        "Return the MASTER resume as a single JSON object with keys: profile, "
        "summary_options, core_skills, ats_adjacent_skills, skills, experience, "
        "projects, education."
    )
    data = provider.json_call(system, user, max_tokens=3200, schema=MASTER_RESUME_SCHEMA)
    return _coerce_master_resume(data)


def _coerce_master_resume(data: dict) -> dict:
    """Normalize an imported master-resume dict to safe, expected shapes."""
    def _list(v) -> list:
        if isinstance(v, list):
            return v
        if isinstance(v, str) and v.strip():
            return [t.strip() for t in v.split(",") if t.strip()]
        return []

    out: dict = {}
    profile = data.get("profile") if isinstance(data.get("profile"), dict) else {}
    titles = [str(t).strip() for t in _list(profile.get("identity_titles")) if str(t).strip()]
    seniority = str(profile.get("seniority", "")).strip() or "professional"
    if titles:
        out["profile"] = {"identity_titles": titles, "seniority": seniority}

    out["summary_options"] = [str(s).strip() for s in _list(data.get("summary_options")) if str(s).strip()]
    out["core_skills"] = [str(s).strip() for s in _list(data.get("core_skills")) if str(s).strip()]
    out["ats_adjacent_skills"] = [str(s).strip() for s in _list(data.get("ats_adjacent_skills")) if str(s).strip()]

    # The schema asks for a {group, items} list because structured output is
    # more reliable with fixed keys, but resume.yaml's canonical shape is a
    # mapping — see src/master_resume.py. Fold it here, at the write boundary,
    # so nothing downstream ever meets the list form.
    out["skills"] = normalize_skills(data.get("skills"))

    def _entries(key, fields):
        rows = []
        for e in _list(data.get(key)):
            if not isinstance(e, dict):
                continue
            row = {}
            for f in fields:
                if f in e and e[f] not in (None, ""):
                    row[f] = e[f]
            if "bullets_all" in e:
                row["bullets_all"] = [str(b).strip() for b in _list(e["bullets_all"]) if str(b).strip()]
            rows.append(row)
        return rows

    out["experience"] = _entries("experience", ("company", "role", "location", "start_date", "end_date"))
    out["projects"] = _entries("projects", ("name", "tech", "link"))
    out["education"] = [
        {k: v for k, v in e.items() if v not in (None, "")}
        for e in _list(data.get("education")) if isinstance(e, dict)
    ]
    return out


def master_resume_to_yaml(data: dict) -> str:
    """Render an imported master-resume dict to YAML in the conventional key
    order, with a short header comment."""
    ordered = {k: data[k] for k in FORM_KEYS if k in data and data[k] not in (None, [], {})}
    body = yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True, default_flow_style=False, width=100)
    header = (
        "# MASTER RESUME: your everything file. The LLM selects and trims per "
        "job.\n# Add bullets liberally (more truthful material = better "
        "tailoring). Review and edit before relying on it.\n\n"
    )
    return header + body


def _coerce_story(data: dict) -> dict:
    """Normalize an LLM story dict to the expected shapes."""
    def _as_list(v) -> list[str]:
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str):
            return [t.strip() for t in v.split(",") if t.strip()]
        return []

    return {
        "title": str(data.get("title", "")).strip(),
        "tags": _as_list(data.get("tags")),
        "role_fit": _as_list(data.get("role_fit")),
        "company_fit": _as_list(data.get("company_fit")),
        "one_liner": str(data.get("one_liner", "")).strip(),
        "body": str(data.get("body", "")).strip(),
    }


def story_dict_to_markdown(story: dict) -> str:
    """Render a story dict to the frontmatter + body markdown format."""
    front = {k: story.get(k) for k in _STORY_KEYS}
    frontmatter = yaml.safe_dump(
        front, sort_keys=False, allow_unicode=True, default_flow_style=False
    ).strip()
    body = str(story.get("body", "")).strip()
    return f"---\n{frontmatter}\n---\n\n{body}\n"


_TWEAK_SYSTEMS = {
    "story": (
        "You revise a candidate 'story' markdown file (YAML frontmatter then a "
        "prose body). Apply the instruction and return the COMPLETE updated "
        "file. Keep the frontmatter keys title, tags, role_fit, company_fit, "
        "one_liner valid and in that order, with '---' fences. " + _GROUNDING
    ),
    "bio": (
        "You revise the candidate's bio/voice reference markdown. Apply the "
        "instruction and return the COMPLETE updated markdown. Preserve the "
        "headings/structure unless asked otherwise. When the instruction refers "
        "to a story below (e.g. mentions an employer, project, or theme covered "
        "by one), pull the real details from that story rather than asking for "
        "them. " + _GROUNDING
    ),
    "resume": (
        "You revise the candidate's master resume YAML. Apply the instruction "
        "and return the COMPLETE updated YAML only (no code fences, no prose). "
        "Keep it valid YAML with the same top-level keys. When the instruction "
        "refers to a story below (e.g. 'add my X internship'), pull the real "
        "employer, dates, and bullets from that story's content rather than "
        "inventing them or leaving placeholders. " + _GROUNDING
    ),
}


def _stories_context(stories: list[dict] | None) -> str:
    if not stories:
        return ""
    block = "\nCANDIDATE'S STORIES (real background — use these for facts/metrics the instruction refers to):\n"
    for s in stories:
        block += (
            f"\n---\nTitle: {s.get('title','')}\n"
            f"Tags: {', '.join(s.get('tags', []))}\n"
            f"One-liner: {s.get('one_liner','')}\n"
            f"{s.get('body','')}\n"
        )
    return block


def tweak_content(
    kind: str, text: str, instruction: str, *, provider, stories: list[dict] | None = None
) -> str:
    """Revise story/bio/resume text per a freeform instruction. Returns the
    new text (the caller validates + persists).

    `stories` (for kind in "resume"/"bio") grounds the edit in the candidate's
    written stories, so e.g. "add my Testsprite internship" can pull the real
    employer/dates/bullets instead of the model inventing or refusing them.
    """
    system = _TWEAK_SYSTEMS.get(kind)
    if system is None:
        raise ValueError(f"unknown content kind: {kind}")
    user = (
        f"CURRENT CONTENT:\n{text}\n"
        f"{_stories_context(stories) if kind in ('resume', 'bio') else ''}\n"
        f"INSTRUCTION:\n{instruction.strip()}\n\n"
        "Return ONLY the complete updated content, nothing else."
    )
    out = provider.text_call(system, user, max_tokens=2400)
    return _strip_code_fence(out).strip() + "\n"


def _strip_code_fence(text: str) -> str:
    """Remove a leading/trailing ``` fence the model sometimes adds."""
    t = text.strip()
    if t.startswith("```"):
        # drop first fence line (``` or ```yaml/markdown) and trailing fence
        t = re.sub(r"^```[a-zA-Z0-9]*\n", "", t)
        t = re.sub(r"\n```$", "", t)
    return t


def load_taxonomy(stories_dir: str | Path) -> str:
    """Return the tag/role/company taxonomy section from stories/_INDEX.md, or
    a small default if absent."""
    index = Path(stories_dir) / "_INDEX.md"
    if index.exists():
        text = index.read_text(encoding="utf-8")
        marker = "## Tag taxonomy"
        if marker in text:
            return text[text.index(marker):].strip()
    return (
        "Technical areas: ai, llm, rag, ml, systems, infrastructure, sre, "
        "full-stack, backend, frontend, data, platform, devtools, security.\n"
        "Role types (role_fit): swe, ml-engineer, ai-engineer, sre, "
        "platform-engineer, full-stack, backend, frontend, product-engineer.\n"
        "Company types (company_fit): finance, startup, bigtech, enterprise, "
        "ai-first, platform, consumer, mission-driven, infrastructure."
    )
