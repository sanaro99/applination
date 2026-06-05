"""Headless browser + structured job data extractor for the manual application flow.

Three separate concerns:
  1. Job metadata  (company, title, location, remote, description)
  2. Application questions  — scraped from actual <label>/<input> form fields
  3. Specific instructions  — short LLM pass over the JD text only
"""
from __future__ import annotations
import json
import logging
import re
from urllib.parse import urlparse

from .providers import LLMProvider
from .scrapers.schema import strip_html

LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Standard field detection
# ---------------------------------------------------------------------------

# Short keywords (matched as substrings against labels ≤ 35 chars).
_SHORT_STANDARD: frozenset[str] = frozenset({
    "first name", "last name", "full name", "name",
    "email", "email address",
    "phone", "phone number", "mobile",
    "resume", "resume/cv", "cv",
    "cover letter",
    "linkedin", "linkedin profile", "linkedin url",
    "website", "personal website",
    "portfolio", "portfolio url",
    "github", "github profile", "github url",
    "twitter",
    "city", "state", "country", "zip", "zip code", "address",
    "school", "university", "degree", "major", "gpa",
    "graduation", "end date", "start year", "end year",
    "salary", "compensation",
})

# Substring patterns always skipped regardless of label length.
_ALWAYS_SKIP: tuple[str, ...] = (
    # Authorization / visa
    "require sponsorship", "visa sponsorship", "visa status",
    "authorized to work", "work authorization", "legally authorized",
    # Demographics (EEO)
    "how did you hear", "how did you find", "referral source",
    "equal opportunity", "eeo",
    "gender", "race", "ethnicity", "veteran status", "disability status",
    "pronouns",
    # Legal / policy acknowledgments
    "agree to", "privacy policy", "terms of", "policy for", "acknowledgment",
    # Generic no-op fields (catch-all text boxes, section headers)
    "additional information",
    "personal preferences",
)


def _is_standard_label(text: str) -> bool:
    t = text.lower().strip()
    if any(pat in t for pat in _ALWAYS_SKIP):
        return True
    # Short-keyword check only for labels ≤ 20 chars (field headings like "GPA",
    # "School", "Country").  Longer text is a sentence/question — only _ALWAYS_SKIP
    # applies, so "Please provide your undergrad GPA:" is kept.
    if len(t) <= 20:
        return any(kw in t for kw in _SHORT_STANDARD)
    return False


def _clean_label(raw: str) -> str:
    """Strip trailing punctuation, asterisks, and '(optional)' noise."""
    s = re.sub(r"\s+", " ", raw).strip()
    s = re.sub(r"[\*\:]+$", "", s).strip()
    s = re.sub(r"\s*\(optional\)\s*$", "", s, flags=re.I).strip()
    return s


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------

class JobExtractor:
    """Extract structured job data from any job posting URL."""

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    # ------------------------------------------------------------------
    def extract(self, url: str) -> dict:
        """Return dict: company, title, location, remote, description,
        additional_questions (list[str]), specific_instructions (str), url."""
        html, text = self._fetch(url)
        platform = _detect_platform(url, html)

        meta = (
            self._try_jsonld(html, url)
            or self._try_heuristics(url, html, platform)
            or self._llm_extract_meta(url, text, html)
        )

        questions = self._get_questions(url, html, platform)
        instructions = self._get_instructions(meta.get("description") or text[:4000])

        return {**meta, "additional_questions": questions, "specific_instructions": instructions}

    # ------------------------------------------------------------------
    # Step 1 — job metadata
    # ------------------------------------------------------------------

    def _try_jsonld(self, html: str, url: str) -> dict | None:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(tag.string or "")
                if isinstance(data, list):
                    data = next(
                        (d for d in data if isinstance(d, dict) and d.get("@type") == "JobPosting"),
                        None,
                    )
                if not data or data.get("@type") != "JobPosting":
                    continue
                result = self._from_jsonld(data, url)
                if result:
                    return result
            except Exception:
                continue
        return None

    def _from_jsonld(self, data: dict, url: str) -> dict | None:
        desc = strip_html(data.get("description", ""))
        if not desc or len(desc) < 100:
            return None
        loc = data.get("jobLocation") or {}
        if isinstance(loc, list):
            loc = loc[0] if loc else {}
        addr = (loc.get("address") or {}) if isinstance(loc, dict) else {}
        city = (addr.get("addressLocality") or addr.get("addressRegion") or "") if isinstance(addr, dict) else str(addr)
        job_loc_type = (data.get("jobLocationType") or "").lower()
        remote = "remote" in desc.lower()[:300] or "telecommute" in job_loc_type or "remote" in job_loc_type
        org = data.get("hiringOrganization") or {}
        company = org.get("name", "") if isinstance(org, dict) else str(org)
        return {"company": company, "title": data.get("title", ""), "location": city,
                "remote": remote, "description": desc, "url": url}

    def _try_heuristics(self, url: str, html: str, platform: str) -> dict | None:
        from bs4 import BeautifulSoup
        parsed = urlparse(url)
        soup = BeautifulSoup(html, "html.parser")
        company = title = location = desc = ""

        if platform == "greenhouse":
            # Title: h1 with section-header class (job-boards format) or older formats
            t = soup.select_one("h1.section-header, h1.app-title, .posting-title h1, h1")
            if t:
                title = t.get_text(strip=True)

            # Location: og:description often holds "City, ST" for Greenhouse
            og_desc = soup.find("meta", property="og:description")
            if og_desc:
                location = (og_desc.get("content") or "").strip()
            if not location:
                loc_el = soup.select_one(".location, .job-location, [class*='location']")
                if loc_el:
                    location = loc_el.get_text(strip=True)

            # Description: extract FIRST so company search can use it
            for sel in [
                ".job__description",           # job-boards.greenhouse.io new format
                ".job-description__text",
                "#job-description",
                "[class*='job__description']",
                "[class*='posting-description']",
                "#content",
                ".content",
            ]:
                d = soup.select_one(sel)
                if d:
                    candidate = strip_html(str(d))
                    if len(candidate) >= 200:
                        desc = candidate
                        break

            # Company: page element → og:site_name → scan description → URL slug
            c = soup.select_one(".company-name, [class*='company-name'], [class*='company__name']")
            if c:
                company = c.get_text(strip=True)
            if not company:
                og_site = soup.find("meta", property="og:site_name")
                if og_site:
                    company = (og_site.get("content") or "").strip()
            if not company:
                slug = parsed.path.strip("/").split("/")[0]
                company = _company_from_slug(slug, desc)

        elif platform == "lever":
            t = soup.select_one(".posting-title h2, h2")
            if t:
                title = t.get_text(strip=True)
            logo = soup.select_one(".main-header-logo img")
            if logo:
                company = (logo.get("alt") or "").strip()
            if not company and soup.title:
                pt = soup.title.string or ""
                company = pt.split(" at ")[-1].strip() if " at " in pt else ""
            loc = soup.select_one(".posting-categories .location")
            if loc:
                location = loc.get_text(strip=True)
            d = soup.select_one(".posting-description, .section-wrapper")
            if d:
                desc = strip_html(str(d))

        if desc and len(desc) >= 200:
            remote = "remote" in (location or "").lower() or "remote" in desc[:300].lower()
            return {"company": company, "title": title, "location": location,
                    "remote": remote, "description": desc, "url": url}
        return None

    def _llm_extract_meta(self, url: str, text: str, html: str) -> dict:
        """XML-tag extraction for metadata; best-effort description from HTML."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        # Try to pull a clean description from HTML before falling back to raw innerText
        desc = ""
        for sel in [".job__description", ".job-description__text", ".posting-description",
                    "[class*='job__description']", "[class*='description']", "main", "article"]:
            d = soup.select_one(sel)
            if d:
                candidate = strip_html(str(d))
                if len(candidate) >= 200:
                    desc = candidate
                    break
        if not desc:
            desc = _clean_page_text(text)

        system = "Extract job metadata. Respond ONLY with the XML tags shown, nothing else."
        prompt = (
            f"URL: {url}\n\n"
            f"PAGE TEXT:\n{text[:4000]}\n\n"
            "<company>company name</company>\n"
            "<title>job title</title>\n"
            "<location>city and state, or empty</location>\n"
            "<remote>true or false</remote>"
        )
        raw = self.provider.text_call(system, prompt, max_tokens=200)
        return {
            "company": _tag(raw, "company"),
            "title": _tag(raw, "title"),
            "location": _tag(raw, "location"),
            "remote": _tag(raw, "remote").lower() in ("true", "yes"),
            "description": desc,
            "url": url,
        }

    # ------------------------------------------------------------------
    # Step 2 — application questions from form fields
    # ------------------------------------------------------------------

    def _get_questions(self, url: str, html: str, platform: str) -> list[str]:
        try:
            if platform == "greenhouse":
                return self._greenhouse_questions(html)
            if platform == "lever":
                return self._lever_questions(url)
            if platform in ("workday", "linkedin", "indeed"):
                return []   # login-gated or bot-blocked
            return _scrape_all_labels(html)
        except Exception as e:
            LOG.warning("Question extraction failed (%s): %s", platform, e)
            return []

    def _greenhouse_questions(self, html: str) -> list[str]:
        """
        Greenhouse custom questions always have for="question_XXXXXXXX".
        This is stable across both boards.greenhouse.io and job-boards.greenhouse.io.
        We use it as a reliable signal instead of fragile CSS class selectors.
        """
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        # Only load an iframe when it actually points to the Greenhouse application
        # form (app.greenhouse.io/applications/...).  The Google Analytics tracker
        # iframe also contains "boards.greenhouse.io" in its fragment, so we must
        # check the src starts with the Greenhouse app domain, not just contains it.
        iframe = soup.select_one("iframe[id='grnhse_app']")
        if not iframe:
            for f in soup.find_all("iframe"):
                src = f.get("src") or ""
                if src.startswith("https://app.greenhouse.io/applications"):
                    iframe = f
                    break
        if iframe:
            src = iframe.get("src") or ""
            if src:
                try:
                    iframe_html, _ = self._fetch(src)
                    soup = BeautifulSoup(iframe_html, "html.parser")
                    LOG.info("Loaded Greenhouse iframe: %s", src)
                except Exception as e:
                    LOG.warning("Failed to load Greenhouse iframe: %s", e)

        seen: set[str] = set()
        questions: list[str] = []

        for label in soup.find_all("label"):
            for_id = label.get("for", "")
            # Only custom questions have for="question_*"
            if not for_id.startswith("question_"):
                continue

            inp = soup.find(id=for_id)
            if inp is None:
                continue

            inp_type = (inp.get("type") or "text").lower()
            # Skip file uploads and buttons; include text, textarea, hidden (custom selects)
            if inp_type in ("file", "submit", "button", "checkbox", "radio"):
                continue

            clean = _clean_label(label.get_text(" ", strip=True))
            if not clean or len(clean) < 5:
                continue
            if _is_standard_label(clean):
                continue
            if clean.lower() in seen:
                continue

            seen.add(clean.lower())
            questions.append(clean)

        return questions

    def _lever_questions(self, url: str) -> list[str]:
        """Lever application form lives at <listing-url>/apply."""
        apply_url = url.split("?")[0].rstrip("/") + "/apply"
        LOG.info("Fetching Lever apply form: %s", apply_url)
        try:
            apply_html, _ = self._fetch(apply_url)
        except Exception as e:
            LOG.warning("Failed to fetch Lever apply page: %s", e)
            return []
        return _scrape_all_labels(apply_html)

    # ------------------------------------------------------------------
    # Step 3 — specific instructions from JD text
    # ------------------------------------------------------------------

    def _get_instructions(self, jd_text: str) -> str:
        """
        Look for explicit submission requirements *in the job description text*.
        Returns empty string when nothing specific is found.

        Counts as instruction: cover letter with specific content, portfolio,
        work samples, code samples, specific file attachments, word limits.
        Does NOT count: standard responsibilities, general job requirements.
        """
        system = (
            "You scan job description text for explicit application submission requirements. "
            "Only report what the posting explicitly tells applicants to include or do "
            "beyond a standard resume. Do not invent or infer."
        )
        user = (
            f"JOB DESCRIPTION:\n{jd_text[:3000]}\n\n"
            "Does this text explicitly tell applicants to include or submit something "
            "specific beyond a standard resume?\n"
            "(e.g. 'cover letter addressing X', 'portfolio required', 'attach work samples', "
            "'500-word essay', 'include GitHub link', 'code challenge will follow')\n\n"
            "<instructions>one or two sentences describing the specific requirement, "
            "or empty if none</instructions>"
        )
        raw = self.provider.text_call(system, user, max_tokens=150)
        found = _tag(raw, "instructions").strip()
        _negatives = ("none", "no specific", "no additional", "standard resume",
                      "not mentioned", "n/a", "nothing specific", "does not mention",
                      "not specified", "not required", "not explicitly")
        if not found or any(neg in found.lower() for neg in _negatives):
            return ""
        return found

    # ------------------------------------------------------------------
    # Browser
    # ------------------------------------------------------------------

    def _fetch(self, url: str) -> tuple[str, str]:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ))
            page.goto(url, wait_until="networkidle", timeout=30_000)
            for sel in [".job__description", ".posting-description", "#job-description",
                        "[class*='description']", "#content", ".job-details"]:
                try:
                    page.wait_for_selector(sel, timeout=3_000)
                    break
                except Exception:
                    continue
            html = page.content()
            text: str = page.evaluate("() => document.body.innerText")
            browser.close()
        return html, text


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _detect_platform(url: str, html: str) -> str:
    host = urlparse(url).hostname or ""
    if "greenhouse.io" in host:
        return "greenhouse"
    if "lever.co" in host:
        return "lever"
    if "workday.com" in host:
        return "workday"
    if "linkedin.com" in host:
        return "linkedin"
    if "indeed.com" in host:
        return "indeed"
    if "grnhse_app" in html or "boards.greenhouse.io" in html:
        return "greenhouse"
    return "generic"


def _scrape_all_labels(html: str) -> list[str]:
    """
    Generic label scraper for any platform.
    Finds all <label> elements, requires an associated visible text input or textarea.
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    questions: list[str] = []

    for label in soup.find_all("label"):
        for_id = label.get("for")
        inp = soup.find(id=for_id) if for_id else label.find(["input", "textarea"])
        if inp is None:
            continue
        inp_type = (inp.get("type") or "text").lower()
        if inp_type in ("file", "hidden", "checkbox", "radio", "submit", "button"):
            continue
        if inp.name == "select":
            continue

        clean = _clean_label(label.get_text(" ", strip=True))
        if not clean or len(clean) < 5:
            continue
        if _is_standard_label(clean):
            continue
        if clean.lower() in seen:
            continue

        seen.add(clean.lower())
        questions.append(clean)

    return questions


def _company_from_slug(slug: str, desc: str) -> str:
    """Derive properly-cased company name from a URL slug.

    Searches the first 1000 chars of the description for a capitalized token
    that normalises to the same string as the slug.  Falls back to title-case
    of the slug when no match is found (e.g. 'my-company' → 'My Company').
    """
    slug_norm = re.sub(r"[\s\-_&,\.]", "", slug).lower()
    for m in re.finditer(r"[A-Z][A-Za-z0-9\-&\.]{1,40}", desc[:1000]):
        candidate = m.group(0).strip()
        if re.sub(r"[\s\-_&,\.]", "", candidate).lower() == slug_norm:
            return candidate
    return slug.replace("-", " ").replace("_", " ").title()


def _tag(text: str, name: str) -> str:
    m = re.search(rf"<{name}>(.*?)</{name}>", text, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _clean_page_text(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text[:8000].strip()
