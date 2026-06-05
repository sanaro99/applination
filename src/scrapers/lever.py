"""
Lever — public job board API.

Many tech companies (Coinbase, Scale AI, Vercel, Replit, etc.) host their
jobs on Lever. Each company's postings are available at:
  https://api.lever.co/v0/postings/{slug}?mode=json

No API key required. Returns all open postings; we filter for internships.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
import logging

import requests

from .schema import Job, strip_html

LOG = logging.getLogger(__name__)
ENDPOINT = "https://api.lever.co/v0/postings/{slug}?mode=json"

# Terms we look for in title/commitment to identify internship roles.
_INTERN_SIGNALS = ["intern", "internship", "co-op", "coop"]


def _is_intern(posting: dict) -> bool:
    title = (posting.get("text") or "").lower()
    commitment = (posting.get("commitment") or "").lower()
    categories = posting.get("categories") or {}
    team = (categories.get("team") or "").lower()
    commitment_cat = (categories.get("commitment") or "").lower()

    return any(
        s in field
        for s in _INTERN_SIGNALS
        for field in [title, commitment, team, commitment_cat]
    )


def _keyword_match(posting: dict, keywords: list[str]) -> bool:
    if not keywords:
        return True
    text = " ".join([
        posting.get("text") or "",
        (posting.get("categories") or {}).get("team") or "",
        (posting.get("descriptionPlain") or "")[:500],
    ]).lower()
    return any(kw.lower() in text for kw in keywords)


def fetch(
    companies: list[str],
    keywords: list[str],
    last_n_hours: int = 24 * 30,   # Lever roles don't turn over daily; default 30 days
) -> list[Job]:
    """
    Fetch internship postings from Lever boards for the given company slugs.

    Args:
        companies: list of Lever slugs (e.g. ["coinbase", "scale-ai", "vercel"])
        keywords: role keywords to filter by
        last_n_hours: only keep postings created within this window
    """
    cutoff_ms = (
        datetime.now(timezone.utc) - timedelta(hours=last_n_hours)
    ).timestamp() * 1000  # Lever uses epoch milliseconds

    out: list[Job] = []
    for slug in companies:
        url = ENDPOINT.format(slug=slug)
        try:
            r = requests.get(url, timeout=20)
            if r.status_code == 404:
                LOG.debug("lever: no board found for slug=%s", slug)
                continue
            r.raise_for_status()
            postings = r.json()
        except Exception as e:
            LOG.warning("lever: fetch failed for slug=%s: %s", slug, e)
            continue

        for p in postings or []:
            if not _is_intern(p):
                continue
            if not _keyword_match(p, keywords):
                continue

            created_at_ms = p.get("createdAt")
            if created_at_ms and created_at_ms < cutoff_ms:
                continue

            posted_at = (
                datetime.fromtimestamp(created_at_ms / 1000, tz=timezone.utc)
                if created_at_ms else None
            )

            categories = p.get("categories") or {}
            location = (
                p.get("workplaceType") or
                categories.get("location") or
                categories.get("allLocations") or
                "Unspecified"
            )
            if isinstance(location, list):
                location = ", ".join(location)

            description = strip_html(
                p.get("description") or p.get("descriptionPlain") or ""
            )
            if not description:
                description = f"{p.get('text','')} internship at {slug.title()}."

            out.append(Job(
                source=f"lever:{slug}",
                company=slug.replace("-", " ").title(),
                title=p.get("text", "").strip(),
                location=str(location),
                url=p.get("hostedUrl") or p.get("applyUrl") or "",
                description=description,
                posted_at=posted_at,
                remote="remote" in str(location).lower(),
                salary="",
                external_id=p.get("id") or "",
            ))

    LOG.info("lever: %d internship postings across %d companies", len(out), len(companies))
    return out
