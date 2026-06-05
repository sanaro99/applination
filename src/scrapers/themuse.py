"""The Muse — free public API. Broad coverage across US companies."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Iterable
import logging

import requests

from .schema import Job, strip_html

LOG = logging.getLogger(__name__)
ENDPOINT = "https://www.themuse.com/api/public/jobs"


def fetch(keywords: list[str], last_n_hours: int = 24, max_pages: int = 3) -> list[Job]:
    """
    The Muse API does not expose free-text search, so we pull recent 'Internship'
    level jobs and then do keyword filtering client-side.
    """
    out: list[Job] = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=last_n_hours)

    for page in range(max_pages):
        try:
            r = requests.get(
                ENDPOINT,
                params={"level": "Internship", "page": page, "descending": "true"},
                timeout=20,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            LOG.warning("themuse fetch failed page=%d: %s", page, e)
            break

        results = data.get("results", [])
        if not results:
            break

        for item in results:
            try:
                posted = datetime.fromisoformat(item["publication_date"].replace("Z", "+00:00"))
            except Exception:
                posted = None
            if posted and posted < cutoff:
                # Results are sorted desc, so once we're past cutoff we can stop.
                return _filter_by_keywords(out, keywords)

            title = (item.get("name") or "").strip()
            locs = item.get("locations", []) or [{"name": "Unspecified"}]
            location = locs[0]["name"] if locs else "Unspecified"
            company = ((item.get("company") or {}).get("name") or "").strip()

            out.append(Job(
                source="themuse",
                company=company,
                title=title,
                location=location,
                url=item.get("refs", {}).get("landing_page", ""),
                description=strip_html(item.get("contents", "")),
                posted_at=posted,
                remote="remote" in location.lower(),
                external_id=str(item.get("id", "")),
            ))

    return _filter_by_keywords(out, keywords)


def _filter_by_keywords(jobs: list[Job], keywords: list[str]) -> list[Job]:
    kws = [k.lower() for k in keywords]
    kept = []
    for j in jobs:
        hay = f"{j.title} {j.description[:1000]}".lower()
        if any(kw in hay for kw in kws):
            kept.append(j)
    LOG.info("themuse: %d jobs (after keyword filter)", len(kept))
    return kept
