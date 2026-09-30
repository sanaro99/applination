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
from ..target_rules import typed_query

LOG = logging.getLogger(__name__)
ENDPOINT = "https://himalayas.app/jobs/api/search"


def fetch(
    keywords: list[str],
    last_n_hours: int = 24,
    country: str = "US",
    max_pages: int = 3,
    job_type: str = "any",
) -> list[Job]:
    out: list[Job] = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=last_n_hours)

    for kw in keywords:
        for page in range(1, max_pages + 1):
            try:
                r = requests.get(
                    ENDPOINT,
                    params={"q": typed_query(kw, job_type) if job_type == "co_op" else kw,
                            "country": country, "sort": "recent", "page": page,
                            **({"employment_type": {
                                "full_time": "Full Time", "part_time": "Part Time",
                                "internship": "Intern", "contract": "Contractor",
                                "temporary": "Temporary",
                            }[job_type]} if job_type not in {"any", "co_op"} else {})},
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
                locations = [
                    str(loc.get("name") or loc.get("alpha2") or "") if isinstance(loc, dict)
                    else str(loc) for loc in locs
                ]
                out.append(Job(
                    source="himalayas",
                    company=(item.get("companyName") or "").strip(),
                    title=(item.get("title") or "").strip(),
                    location=", ".join(filter(None, locations)) if locs else "Remote (worldwide)",
                    url=item.get("applicationLink", ""),
                    description=strip_html(item.get("description", "")),
                    posted_at=posted,
                    remote=True,
                    salary=_salary_str(item),
                    external_id=item.get("guid", ""),
                    employment_type=str(item.get("employmentType") or ""),
                ))

            if stop:
                break

    LOG.info("himalayas: %d jobs", len(out))
    return out


def _parse_epoch(ts) -> Optional[datetime]:
    if not ts:
        return None
    try:
        if isinstance(ts, str) and not ts.isdigit():
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        epoch = float(ts)
        return datetime.fromtimestamp(epoch / 1000 if epoch > 100_000_000_000 else epoch,
                                      tz=timezone.utc)
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
