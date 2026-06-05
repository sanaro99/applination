"""Remotive — free public JSON API. Remote jobs only."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Iterable
import logging

import requests

from .schema import Job, strip_html

LOG = logging.getLogger(__name__)
ENDPOINT = "https://remotive.com/api/remote-jobs"


def fetch(keywords: list[str], last_n_hours: int = 24, limit: int = 200) -> list[Job]:
    out: list[Job] = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=last_n_hours)

    for kw in keywords:
        try:
            r = requests.get(ENDPOINT, params={"search": kw, "limit": limit}, timeout=20)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            LOG.warning("remotive fetch failed for %r: %s", kw, e)
            continue

        for item in data.get("jobs", []):
            try:
                dt = datetime.fromisoformat(item["publication_date"].replace("Z", "+00:00"))
                # Ensure timezone-aware (assume UTC if naive)
                posted = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                posted = None
            if posted and posted < cutoff:
                continue

            title = item.get("title", "")
            if "intern" not in title.lower() and "intern" not in kw.lower():
                # Remotive returns a lot of non-intern stuff; filter.
                continue

            out.append(Job(
                source="remotive",
                company=item.get("company_name", "").strip(),
                title=title.strip(),
                location=item.get("candidate_required_location", "Remote"),
                url=item.get("url", ""),
                description=strip_html(item.get("description", "")),
                posted_at=posted,
                remote=True,
                salary=item.get("salary", "") or "",
                external_id=str(item.get("id", "")),
            ))
    LOG.info("remotive: %d jobs", len(out))
    return out
