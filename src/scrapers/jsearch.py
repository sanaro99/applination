"""
JSearch (RapidAPI) — aggregates LinkedIn, Indeed, Glassdoor, ZipRecruiter legally.
Free tier: 200 requests/month. Sign up at https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch

NOTE: You need a RapidAPI key for JSearch specifically — not a Gemini or NIM key.
Get it at: https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch

API conservation: we make 1 call per country (not 1 per keyword × country) using
a combined query built from your saved keywords. This uses
~10× fewer requests, keeping you well within the 200 req/month free tier.
"""
from __future__ import annotations
import time
from datetime import datetime, timezone, timedelta
import logging

import requests

from .schema import Job, strip_html

LOG = logging.getLogger(__name__)
ENDPOINT = "https://jsearch.p.rapidapi.com/search"

# How many pages to fetch per country. Each page = 10 results. 3 pages = 30 results.
_PAGES = 3


def fetch(
    keywords: list[str],
    rapidapi_key: str,
    countries: list[str] = ["us"],
    last_n_hours: int = 24,
) -> list[Job]:
    if not rapidapi_key:
        LOG.info("jsearch: key not set, skipping")
        return []

    # Detect obviously wrong key types and warn rather than burning quota.
    if rapidapi_key.startswith("nvapi-"):
        LOG.warning(
            "jsearch: the configured key looks like an NVIDIA NIM key (starts with 'nvapi-'), "
            "not a RapidAPI key. Get a JSearch key at rapidapi.com and update "
            "sources.jsearch.rapidapi_key in config.yaml. Skipping JSearch."
        )
        return []

    out: list[Job] = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=last_n_hours)
    date_posted = "today" if last_n_hours <= 24 else "3days" if last_n_hours <= 72 else "week"

    headers = {
        "x-rapidapi-key": rapidapi_key,
        "x-rapidapi-host": "jsearch.p.rapidapi.com",
    }

    for country in countries:
        for page in range(1, _PAGES + 1):
            try:
                r = requests.get(
                    ENDPOINT,
                    headers=headers,
                    params={
                        "query": f"{' OR '.join(keywords) or 'jobs'} in {country}",
                        "page": str(page),
                        "num_pages": "1",
                        "date_posted": date_posted,
                    },
                    timeout=25,
                )
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                LOG.warning("jsearch fetch failed (page %d, country %s): %s", page, country, e)
                break  # stop paging on error

            items = data.get("data", []) or []
            if not items:
                break  # no more results

            for item in items:
                title = (item.get("job_title") or "").strip()

                posted_epoch = item.get("job_posted_at_timestamp")
                posted = (
                    datetime.fromtimestamp(int(posted_epoch), tz=timezone.utc)
                    if posted_epoch else None
                )
                if posted and posted < cutoff:
                    continue

                location = ", ".join(filter(None, [
                    item.get("job_city"), item.get("job_state"), item.get("job_country")
                ])) or "Unspecified"

                out.append(Job(
                    source="jsearch",
                    company=(item.get("employer_name") or "").strip(),
                    title=title,
                    location=location,
                    url=item.get("job_apply_link") or item.get("job_google_link") or "",
                    description=strip_html(item.get("job_description", "")),
                    posted_at=posted,
                    remote=bool(item.get("job_is_remote")),
                    salary=(
                        f"{item.get('job_min_salary','')}-{item.get('job_max_salary','')}"
                        if item.get("job_min_salary") else ""
                    ),
                    external_id=str(item.get("job_id", "")),
                ))

            # Brief pause between pages to be kind to the API
            if page < _PAGES:
                time.sleep(0.5)

    LOG.info("jsearch: %d jobs", len(out))
    return out
