"""
SimplifyJobs / Pitt CSC — Summer 2026 Internship List

Fetches the community-maintained GitHub list at:
  https://github.com/SimplifyJobs/Summer2026-Internships

Updated daily by contributors + the Simplify team. Covers 1000+ roles across
SWE, PM, Data/AI/ML, Quant, and Hardware sections. No API key required.

Parsing strategy: the README uses HTML <table> blocks (not markdown tables).
Each <tr> is one role. Sub-rows (company cell = "↳") inherit the company
from the previous named row. Closed positions have 🔒 in the role cell
(or no Apply link) — these are skipped.
"""
from __future__ import annotations
import hashlib
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

from .schema import Job, strip_html

LOG = logging.getLogger(__name__)

RAW_URL = (
    "https://raw.githubusercontent.com/"
    "SimplifyJobs/Summer2026-Internships/dev/README.md"
)

# Roles we explicitly don't want (hardware, quant finance only sections)
_SKIP_SECTIONS = {"hardware engineering"}

# Minimum keywords that should appear somewhere in title to be relevant.
# If user keywords are set, those override this; this is just a relevance guard.
_RELEVANT_ROLE_TERMS = {
    "software", "engineer", "engineering", "developer", "swe",
    "ml", "machine learning", "ai", "artificial intelligence",
    "data science", "data scientist", "data engineer",
    "product manager", "product management", "pm",
    "site reliability", "sre", "platform", "backend", "frontend",
    "full stack", "fullstack", "research", "nlp", "llm",
    "intern",  # catch-all: if it says intern anywhere, probably relevant
}


def _extract_company(td_html: str) -> Optional[str]:
    """Extract company name from a Company <td>. Returns None for sub-rows (↳)."""
    text = _strip_tags(td_html).strip()
    if text.startswith("↳") or text == "":
        return None
    # strip emoji/badges that sometimes prefix company names
    text = re.sub(r"[\U0001F300-\U0001FFFF\u2600-\u26FF\u2700-\u27BF🔥]", "", text)
    return text.strip() or None


def _extract_apply_url(td_html: str) -> str:
    """Extract the direct Apply URL (alt='Apply' image link) from Application td."""
    m = re.search(r'<a\s+href="([^"]+)"[^>]*>\s*<img[^>]+alt="Apply"', td_html, re.I)
    if m:
        return m.group(1)
    return ""


def _strip_tags(html: str) -> str:
    """Remove all HTML tags and decode common entities."""
    text = re.sub(r"<[^>]+>", "", html)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&#39;", "'").replace("&quot;", '"').replace("&nbsp;", " ")
    return text


def _is_closed(role_html: str, app_html: str) -> bool:
    """Return True if this listing is closed (no Apply button or 🔒 in role)."""
    if "🔒" in role_html:
        return True
    if 'alt="Apply"' not in app_html and 'alt="apply"' not in app_html.lower():
        return True
    return False


def _age_days(age_td: str) -> Optional[int]:
    """Parse '3d' → 3, '14d' → 14. Returns None if unparseable."""
    text = _strip_tags(age_td).strip()
    m = re.match(r"^(\d+)d$", text)
    return int(m.group(1)) if m else None


def _section_name(heading: str) -> str:
    """Extract section type from a heading like '## 💻 Software Engineering Internship Roles'."""
    text = _strip_tags(heading)
    text = re.sub(r"[^\w\s]", " ", text)
    return text.lower().strip()


def _split_tds(row_html: str) -> list[str]:
    """Split a <tr> into its <td> inner-HTML strings."""
    return re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.DOTALL | re.I)


def fetch(
    keywords: list[str],
    max_age_days: int = 14,
    us_only: bool = True,
) -> list[Job]:
    """
    Fetch summer 2026 internships from the SimplifyJobs GitHub list.

    Args:
        keywords: role keywords to filter by (case-insensitive substring match
                  on role title). If empty, returns all non-closed roles.
        max_age_days: skip roles older than this many days (Age column).
                      Set to a large number (e.g. 9999) to get everything.
        us_only: if True, skip roles whose location looks non-US.
    """
    try:
        resp = requests.get(RAW_URL, timeout=30)
        resp.raise_for_status()
        content = resp.text
    except Exception as e:
        LOG.warning("simplify_github: fetch failed: %s", e)
        return []

    kw_lower = [k.lower() for k in keywords] if keywords else []
    out: list[Job] = []
    current_company: str = ""
    current_section: str = ""

    # Walk through all <tr> blocks in document order, tracking section headings.
    # We interleave heading detection with row parsing.
    pos = 0
    row_pattern = re.compile(r"<tr>(.*?)</tr>", re.DOTALL | re.I)
    heading_pattern = re.compile(r"##[^#][^\n]*", re.I)

    # Build a list of (position, type, content) events sorted by position.
    events: list[tuple[int, str, str]] = []
    for m in heading_pattern.finditer(content):
        events.append((m.start(), "heading", m.group(0)))
    for m in row_pattern.finditer(content):
        events.append((m.start(), "row", m.group(1)))
    events.sort(key=lambda x: x[0])

    for _, kind, text in events:
        if kind == "heading":
            current_section = _section_name(text)
            # Reset company on new section
            current_company = ""
            continue

        # Skip hardware / quant sections unless a keyword matches
        if any(skip in current_section for skip in _SKIP_SECTIONS):
            continue

        tds = _split_tds(text)
        if len(tds) < 4:
            continue  # header row or malformed

        company_td, role_td, loc_td, app_td = tds[0], tds[1], tds[2], tds[3]
        age_td = tds[4] if len(tds) > 4 else ""

        # Skip closed
        if _is_closed(role_td, app_td):
            continue

        # Company resolution
        company = _extract_company(company_td)
        if company:
            current_company = company
        elif not current_company:
            continue  # sub-row before we've seen a named row — skip

        role = _strip_tags(role_td).strip()
        # Clean emojis/badges from role title (keep the text)
        role = re.sub(r"[\U0001F1E0-\U0001F9FF\u2600-\u27BF]", "", role).strip()
        if not role:
            continue

        location = _strip_tags(loc_td).strip()

        # US-only filter
        if us_only and location:
            loc_lower = location.lower()
            # Skip if location looks clearly non-US
            non_us_signals = ["canada", " uk", "london", "germany", "india",
                              "australia", "singapore", "japan", "china",
                              "france", "netherlands", "ireland", "poland"]
            if any(sig in loc_lower for sig in non_us_signals):
                continue

        # Age filter
        age = _age_days(age_td)
        if age is not None and age > max_age_days:
            continue

        # Keyword filter (on role title)
        role_lower = role.lower()
        if kw_lower:
            if not any(kw in role_lower for kw in kw_lower):
                continue
        else:
            # No keywords given: keep only roles that look relevant
            if not any(term in role_lower for term in _RELEVANT_ROLE_TERMS):
                continue

        apply_url = _extract_apply_url(app_td)
        description = _enrich_description(apply_url, role, current_company, location)

        out.append(Job(
            source="simplify_github",
            company=current_company,
            title=role,
            location=location,
            url=apply_url,
            description=description,
            posted_at=None,   # no full timestamp; age is in days only
            remote="remote" in location.lower(),
            salary="",
            external_id=f"simplify:{current_company}:{role}:{location}",
        ))

    LOG.info("simplify_github: %d open roles (max_age=%dd)", len(out), max_age_days)
    return out


# ---------------------------------------------------------------------------
# JD enrichment
# ---------------------------------------------------------------------------

_GH_BOARDS_RE = re.compile(
    r"job-boards\.greenhouse\.io/([^/]+)/jobs/(\d+)", re.I
)
_GH_ALT_RE = re.compile(
    r"boards\.greenhouse\.io/([^/]+)/jobs/(\d+)", re.I
)
_LEVER_RE = re.compile(
    r"jobs\.lever\.co/([^/]+)/([0-9a-fA-F\-]+)", re.I
)
_ASHBY_RE = re.compile(
    r"jobs\.ashbyhq\.com/([^/]+)/([0-9a-fA-F\-]+)", re.I
)

# 24h disk cache so re-running the bot doesn't re-hit the same ATS APIs.
# Cache lives under output/.jd_cache/{sha1(url)}.txt — small, easy to wipe.
_JD_CACHE_DIR = Path(__file__).resolve().parents[2] / "output" / ".jd_cache"
_JD_CACHE_TTL_SECS = 24 * 60 * 60
_HTTP_TIMEOUT = 10
_POLITE_UA = (
    "internship_bot/1.0 (https://github.com/sanaro99; daily JD enrichment)"
)


def _cache_path(url: str) -> Path:
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return _JD_CACHE_DIR / f"{h}.txt"


def _cache_get(url: str) -> Optional[str]:
    p = _cache_path(url)
    if not p.exists():
        return None
    age = time.time() - p.stat().st_mtime
    if age > _JD_CACHE_TTL_SECS:
        return None
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _cache_put(url: str, text: str) -> None:
    try:
        _JD_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(url).write_text(text, encoding="utf-8")
    except Exception as e:
        LOG.debug("jd_cache write failed for %s: %s", url, e)


def _http_get_json(url: str, **kwargs) -> Optional[dict]:
    """GET url with one retry, polite UA, JSON return; None on any failure."""
    headers = {"User-Agent": _POLITE_UA, "Accept": "application/json"}
    for attempt in range(2):
        try:
            r = requests.get(url, headers=headers, timeout=_HTTP_TIMEOUT, **kwargs)
            if r.ok:
                return r.json()
        except Exception as e:
            if attempt == 1:
                LOG.debug("JD enrichment GET failed for %s: %s", url, e)
    return None


def _greenhouse_jd(slug: str, job_id: str) -> Optional[str]:
    data = _http_get_json(
        f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}",
        params={"content": "true"},
    )
    if not data:
        return None
    raw = data.get("content") or data.get("description") or ""
    import html as _html
    text = strip_html(_html.unescape(raw)).strip()
    return text if len(text) > 100 else None


def _lever_jd(slug: str, posting_id: str) -> Optional[str]:
    import html as _html
    data = _http_get_json(
        f"https://api.lever.co/v0/postings/{slug}/{posting_id}"
    )
    if not data:
        return None
    parts: list[str] = []
    for fld in ("description", "descriptionPlain"):
        v = data.get(fld)
        if isinstance(v, str) and v.strip():
            parts.append(strip_html(_html.unescape(v)).strip())
            break
    # Lever stores additional sections (responsibilities, requirements) in `lists`.
    for entry in data.get("lists", []) or []:
        if not isinstance(entry, dict):
            continue
        title = (entry.get("text") or "").strip()
        content = entry.get("content") or ""
        body = strip_html(_html.unescape(content)).strip()
        if title and body:
            parts.append(f"{title}\n{body}")
        elif body:
            parts.append(body)
    additional = (data.get("additional") or "").strip()
    if additional:
        parts.append(strip_html(_html.unescape(additional)).strip())
    text = "\n\n".join(p for p in parts if p)
    return text if len(text) > 100 else None


# In-memory cache for Ashby's job-board responses — each is large (~2MB) and
# contains every open posting for the company, so one fetch serves all
# enrichment lookups for that slug within the run.
_ASHBY_BOARD_CACHE: dict[str, dict] = {}


def _ashby_jd(slug: str, job_id: str) -> Optional[str]:
    import html as _html
    board = _ASHBY_BOARD_CACHE.get(slug)
    if board is None:
        data = _http_get_json(
            f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
            params={"includeCompensation": "false"},
        )
        if not data:
            return None
        board = {j.get("id"): j for j in (data.get("jobs") or []) if isinstance(j, dict)}
        _ASHBY_BOARD_CACHE[slug] = board
    jp = board.get(job_id)
    if not jp:
        return None
    text = (jp.get("descriptionPlain") or "").strip()
    if not text:
        html_v = jp.get("descriptionHtml") or ""
        text = strip_html(_html.unescape(html_v)).strip()
    return text if len(text) > 100 else None


def _enrich_description(apply_url: str, role: str, company: str, location: str) -> str:
    """Try to fetch a real JD for this listing.

    Supports:
    - Greenhouse (boards-api.greenhouse.io)
    - Lever (api.lever.co/v0/postings/{slug}/{id})
    - Ashby (api.ashbyhq.com/posting-api/job-board/{slug})

    Falls back to a minimal stub for other ATS systems (Workday, Wellfound,
    custom pages) so we always have enough context for the LLM ranker/tailor.
    Results are cached on disk for 24h so re-runs are cheap.
    """
    stub = f"{role} at {company} ({location})."

    if not apply_url:
        return stub

    cached = _cache_get(apply_url)
    if cached is not None:
        return cached if cached else stub

    text: Optional[str] = None

    for pattern in (_GH_BOARDS_RE, _GH_ALT_RE):
        m = pattern.search(apply_url)
        if m:
            text = _greenhouse_jd(m.group(1), m.group(2))
            break

    if text is None:
        m = _LEVER_RE.search(apply_url)
        if m:
            text = _lever_jd(m.group(1), m.group(2))

    if text is None:
        m = _ASHBY_RE.search(apply_url)
        if m:
            text = _ashby_jd(m.group(1), m.group(2))

    if text:
        capped = text[:4000]
        _cache_put(apply_url, capped)
        return capped

    # Cache the negative result so we don't re-hit failed URLs all day.
    _cache_put(apply_url, "")
    return stub
