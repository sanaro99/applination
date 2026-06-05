"""Common job schema used by all scrapers."""
from __future__ import annotations
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Optional
import hashlib
import re


def dedupe_key(company: str, title: str) -> str:
    """Stable identity for a posting across runs/sources.

    Company + title only, lowercased — robust to tracking params and source
    differences. Shared by ``Job.dedupe_key`` (engine) and the server's DB
    layer so cross-run de-duplication agrees on what "the same job" means.
    """
    base = f"{(company or '').strip().lower()}|{(title or '').strip().lower()}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


@dataclass
class Job:
    source: str                       # e.g. "remotive", "greenhouse:airbnb"
    company: str
    title: str
    location: str
    url: str
    description: str                  # full JD text (plain-ish). Used for tailoring.
    posted_at: Optional[datetime] = None   # timezone-aware UTC
    remote: bool = False
    salary: str = ""
    external_id: str = ""             # source's own id, if any
    match_score: int = 0              # filled in later by ranker
    match_reason: str = ""            # short explanation from ranker
    additional_questions: list[str] = field(default_factory=list)
    specific_instructions: str = ""

    def dedupe_key(self) -> str:
        return dedupe_key(self.company, self.title)

    def safe_folder_name(self) -> str:
        raw = f"{self.company}_{self.title}"
        raw = re.sub(r"[^A-Za-z0-9_\- ]+", "", raw).strip()
        raw = re.sub(r"\s+", "_", raw)
        return raw[:80]

    def to_row(self) -> dict:
        d = asdict(self)
        d["posted_at"] = self.posted_at.isoformat() if self.posted_at else ""
        d["additional_questions"] = "; ".join(self.additional_questions) if self.additional_questions else ""
        return d


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def strip_html(html: str) -> str:
    """Very light HTML-to-text. Good enough for LLM consumption."""
    if not html:
        return ""
    text = re.sub(r"<\s*br\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"</\s*p\s*>", "\n\n", text, flags=re.I)
    text = re.sub(r"</\s*li\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()
