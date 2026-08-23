"""Himalayas — free public JSON API, no key required. Remote jobs only.

Unlike Greenhouse/Lever, this is a real keyword search across many companies —
no per-company slug list to curate. https://himalayas.app/docs/remote-jobs-api
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Optional
import logging

import requests

from .schema import Job, strip_html

LOG = logging.getLogger(__name__)
ENDPOINT = "https://himalayas.app/jobs/api/search"


def fetch(
    keywords: list[str],
    last_n_hours: int = 24,
    country: str = "US",
    max_pages: int = 3,
) -> list[Job]:
    out: list[Job] = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=last_n_hours)

    for kw in keywords:
        for page in range(1, max_pages + 1):
            try:
                r = requests.get(
                    ENDPOINT,
                    params={"q": kw, "country": country, "sort": "recent", "page": page},
                    timeout=20,
                )
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                LOG.warning("himalayas fetch failed for %r page=%d: %s", kw, page, e)
                break

            jobs = data.get("jobs", [])
            if not jobs:
                break

            stop = False
            for item in jobs:
                posted = _parse_epoch(item.get("pubDate"))
                if posted and posted < cutoff:
                    # Results are sorted by recency, so once we're past cutoff
                    # every later item on this page (and further pages) is too.
                    stop = True
                    break

                locs = item.get("locationRestrictions") or []
                out.append(Job(
                    source="himalayas",
                    company=(item.get("companyName") or "").strip(),
                    title=(item.get("title") or "").strip(),
                    location=", ".join(locs) if locs else "Remote (worldwide)",
                    url=item.get("applicationLink", ""),
                    description=strip_html(item.get("description", "")),
                    posted_at=posted,
                    remote=True,
                    salary=_salary_str(item),
                    external_id=item.get("guid", ""),
                ))

            if stop:
                break

    LOG.info("himalayas: %d jobs", len(out))
    return out


def _parse_epoch(ts) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except Exception:
        return None


def _salary_str(item: dict) -> str:
    lo, hi, cur = item.get("minSalary"), item.get("maxSalary"), item.get("currency")
    if not lo and not hi:
        return ""
    parts = [str(v) for v in (lo, hi) if v]
    rng = "-".join(parts)
    period = item.get("salaryPeriod", "")
    return f"{cur or ''} {rng} {period}".strip()
