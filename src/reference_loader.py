"""
reference_loader — story and cover letter example matching.

Two pairs of functions:
  - load_stories / match_stories     : pick the 1-2 most relevant story files
  - load_example_letters / match_example_letter : pick a style-anchor past letter

Scoring is intentionally simple: tag-overlap × 2 + keyword hits in body × 1.
No embeddings, no extra dependencies.
"""
from __future__ import annotations
import logging
import re
from pathlib import Path

LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split a markdown file into (frontmatter_dict, body).

    Expects the file to start with '---\\n...\\n---\\n'.
    Returns ({}, full_text) if no frontmatter found.
    """
    import yaml  # local import — already a project dependency

    if not text.startswith("---"):
        return {}, text

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text

    try:
        fm = yaml.safe_load(parts[1]) or {}
    except Exception:
        fm = {}

    body = parts[2].strip()
    return fm, body


def _tokenize(text: str) -> set[str]:
    """Lowercase word tokens from text, length ≥ 3."""
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 3}


# Map a role category to (title keywords that imply it, story tags that fit it).
# Used by _score to enforce specialization: an ML role should match ML stories,
# not a long mentorship story that happens to share generic tokens like
# "engineers" or "python". Detection is by substring on the role/title text.
_ROLE_CATEGORIES: dict[str, dict[str, list[str]]] = {
    "ml": {
        "title_keywords": [
            "machine learning", "ml ", " ml", "ml-", "ai ", " ai", "artificial intelligence",
            "deep learning", "nlp", "computer vision", "multimodal", "generative",
            "data scien", "applied scientist", "research scientist", "model",
            "llm", "genai", "agentic",
        ],
        "story_tags": [
            "ai", "ml", "ml-engineer", "ai-engineer", "llm", "nlp", "computer-vision",
            "rag", "prompt-engineering", "ai-infrastructure", "agentic", "multi-step-agents",
            "research", "ai-first",
        ],
    },
    "backend": {
        "title_keywords": [
            "backend", "back end", "back-end", "platform", "infrastructure",
            "distributed systems", "systems engineer", "foundation", "api ",
        ],
        "story_tags": [
            "platform", "platform-engineer", "fastapi", "automation", "ai-infrastructure",
            "ubs", "self-hosted", "infrastructure",
        ],
    },
    "frontend": {
        "title_keywords": ["frontend", "front end", "front-end", "ui ", "web "],
        "story_tags": ["react", "frontend", "full-stack", "next.js"],
    },
    "fullstack": {
        "title_keywords": ["full stack", "full-stack", "fullstack", "software engineer"],
        "story_tags": ["full-stack", "fastapi", "react", "next.js", "swe"],
    },
    "sre": {
        "title_keywords": ["sre", "site reliability", "devops", "observability", "reliability"],
        "story_tags": ["sre", "monitoring", "observability", "incident", "automation",
                       "self-hosted"],
    },
    "security": {
        "title_keywords": ["security", "appsec", "infosec", "threat"],
        "story_tags": ["security", "privacy", "compliance", "ethics", "regulatory"],
    },
    "pm": {
        "title_keywords": ["product manager", "product management", "pm ", "associate pm"],
        "story_tags": ["product", "product-management", "user-research", "strategy"],
    },
    "accessibility": {
        "title_keywords": ["accessibility", "a11y", "inclusive", "human-centered", "hci"],
        "story_tags": ["accessibility", "information-equity", "social-impact",
                       "ethics", "inclusion"],
    },
}

# Stories whose tags fall in this category are "people/teaching focused" and
# only fit roles that explicitly call for it. For any pure tech role, we
# multiply their score by 0.4 so they can't outrank a domain-matched story.
_PEOPLE_FIRST_TAGS: set[str] = {"mentorship", "teaching", "soft-skills", "people",
                                "dei", "diversity", "community"}
_PEOPLE_FRIENDLY_ROLE_HINTS: tuple[str, ...] = (
    "developer relations", "devrel", "evangelist", "advocate", "intern manager",
    "mentor", "teaching", "instructor", "people lead",
)


def _detect_role_categories(role: str, jd_text: str) -> set[str]:
    """Return the set of role-category keys (ml/backend/...) that fit this role.

    Matches title_keywords as substrings against the lowercased role+JD text.
    A title can land in multiple categories ("ML Platform Engineer" → ml, backend).
    """
    haystack = (role + " " + jd_text).lower()
    cats: set[str] = set()
    for cat, spec in _ROLE_CATEGORIES.items():
        if any(kw in haystack for kw in spec["title_keywords"]):
            cats.add(cat)
    return cats


def _score(fm: dict, body: str, jd_text: str, company: str, role: str) -> float:
    """Score a story/letter against a JD.

    Tag overlap dominates so a long story body can't outweigh signal:
      - +5 per story tag/role_fit matching a detected role category
      - +2 per tag whose tokens overlap the JD vocabulary
      - +1.5 per role_fit whose tokens overlap the role title
      - +1 per company_fit whose tokens overlap the company name
      - +0.25 per unique body keyword found in the JD (capped weight)
      - ×0.4 penalty if story is people-first but role is not people-friendly
    """
    score = 0.0
    jd_tokens = _tokenize(jd_text + " " + company + " " + role)
    body_tokens = _tokenize(body)

    role_cats = _detect_role_categories(role, jd_text)
    story_tag_strings = {str(t).lower().strip() for t in fm.get("tags", [])}
    role_fit_strings = {str(t).lower().strip() for t in fm.get("role_fit", [])}
    combined_specialization_strings = story_tag_strings | role_fit_strings

    # Category-aware bonus: +5 per overlap between detected categories and
    # the story's domain tags/role_fit.
    for cat in role_cats:
        matching = _ROLE_CATEGORIES[cat]["story_tags"]
        for needle in matching:
            if needle.lower() in combined_specialization_strings:
                score += 5.0

    # Generic tag overlap against JD vocabulary.
    tags = [t.lower().replace("-", " ") for t in fm.get("tags", [])]
    for tag in tags:
        tag_tokens = _tokenize(tag)
        if tag_tokens & jd_tokens:
            score += 2.0

    # role_fit match against role string.
    role_tokens = _tokenize(role)
    for rf in fm.get("role_fit", []):
        if _tokenize(rf) & role_tokens:
            score += 1.5

    # company_fit match against company string.
    company_tokens = _tokenize(company)
    for cf in fm.get("company_fit", []):
        if _tokenize(cf) & company_tokens:
            score += 1.0

    # Keyword hits in story body (capped weight so long bodies don't dominate).
    score += 0.25 * len(body_tokens & jd_tokens)

    # People-first stories: dampen for pure tech roles so a mentorship story
    # can't win an ML or backend internship just because its body is long
    # and contains generic tech vocabulary.
    if story_tag_strings & _PEOPLE_FIRST_TAGS:
        role_lower = (role + " " + jd_text).lower()
        is_people_friendly_role = any(
            hint in role_lower for hint in _PEOPLE_FRIENDLY_ROLE_HINTS
        )
        is_tech_role = bool(role_cats - {"pm", "accessibility"})
        if is_tech_role and not is_people_friendly_role:
            score *= 0.4

    return score


# ---------------------------------------------------------------------------
# Stories
# ---------------------------------------------------------------------------

def load_stories(stories_dir: str | Path) -> list[dict]:
    """Parse all .md story files (skipping _INDEX.md).

    Returns list of dicts with keys:
      title, tags, role_fit, company_fit, one_liner, body
    """
    stories_dir = Path(stories_dir)
    stories = []
    for path in sorted(stories_dir.glob("*.md")):
        if path.name.startswith("_"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
            fm, body = _parse_frontmatter(text)
            stories.append({
                "title": fm.get("title", path.stem),
                "tags": fm.get("tags", []),
                "role_fit": fm.get("role_fit", []),
                "company_fit": fm.get("company_fit", []),
                "one_liner": fm.get("one_liner", ""),
                "body": body,
                "_path": str(path),
            })
        except Exception as e:
            LOG.warning("Could not load story %s: %s", path.name, e)
    return stories


def match_stories(
    jd_text: str,
    company: str,
    role: str,
    stories: list[dict],
    top_k: int = 2,
) -> list[dict]:
    """Return the top_k stories most relevant to this JD/company/role."""
    if not stories:
        return []

    scored = [
        (s, _score(s, s.get("body", ""), jd_text, company, role))
        for s in stories
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [s for s, _ in scored[:top_k]]


# ---------------------------------------------------------------------------
# Cover letter examples
# ---------------------------------------------------------------------------

def load_example_letters(examples_dir: str | Path) -> list[dict]:
    """Load past cover letters from examples_dir.

    Each .md file may have optional frontmatter with 'tags', 'company', 'role'.
    Returns list of dicts: {title, tags, company, role, body, _path}
    """
    examples_dir = Path(examples_dir)
    if not examples_dir.exists():
        return []

    letters = []
    for path in sorted(examples_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
            fm, body = _parse_frontmatter(text)
            letters.append({
                "title": fm.get("title", path.stem),
                "tags": fm.get("tags", []),
                "company": fm.get("company", ""),
                "role": fm.get("role", ""),
                "body": body,
                "_path": str(path),
            })
        except Exception as e:
            LOG.warning("Could not load example letter %s: %s", path.name, e)
    return letters


def match_example_letter(
    jd_text: str,
    company: str,
    role: str,
    examples: list[dict],
) -> str | None:
    """Return the body of the best-matching example letter, or None if none exist."""
    if not examples:
        return None

    scored = [
        (e, _score(e, e.get("body", ""), jd_text, company, role))
        for e in examples
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    best, best_score = scored[0]

    # Only use an example if it has a meaningful match (score > 0)
    if best_score <= 0:
        return None

    return best.get("body", "") or None


# ---------------------------------------------------------------------------
# Guidelines (resume writing guidelines as RAG)
# ---------------------------------------------------------------------------

def load_guidelines(guidelines_dir: str | Path) -> list[dict]:
    """Parse all .md guideline files from guidelines_dir.

    Returns list of dicts with keys:
      title, tags, role_fit, applies_when, body, _path
    """
    guidelines_dir = Path(guidelines_dir)
    if not guidelines_dir.exists():
        return []

    guidelines = []
    for path in sorted(guidelines_dir.glob("*.md")):
        if path.name.startswith("_"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
            fm, body = _parse_frontmatter(text)
            guidelines.append({
                "title": fm.get("title", path.stem),
                "tags": fm.get("tags", []),
                "role_fit": fm.get("role_fit", []),
                "applies_when": fm.get("applies_when", ""),
                "body": body,
                "_path": str(path),
            })
        except Exception as e:
            LOG.warning("Could not load guideline %s: %s", path.name, e)
    return guidelines


def match_guidelines(
    jd_text: str,
    role: str,
    guidelines: list[dict],
    top_k: int = 3,
) -> list[dict]:
    """Return the top_k guideline docs most relevant to this JD/role."""
    if not guidelines:
        return []

    scored = [
        (g, _score(g, g.get("body", ""), jd_text, "", role))
        for g in guidelines
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [g for g, _ in scored[:top_k]]
