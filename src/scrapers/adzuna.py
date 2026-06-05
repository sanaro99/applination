"""Adzuna — free API with registration at https://developer.adzuna.com."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
import logging

import requests

from .schema import Job, strip_html

LOG = logging.getLogger(__name__)
ENDPOINT_TMPL = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"


def fetch(
    keywords: list[str],
    app_id: str,
    app_key: str,
    countries: list[str] = ["us"],
    last_n_hours: int = 24,
    results_per_keyword: int = 50,
) -> list[Job]:
    if not app_id or not app_key:
        LOG.info("adzuna: keys not set, skipping")
        return []

    out: list[Job] = []
    max_days_old = max(1, last_n_hours // 24)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=last_n_hours)

    for country in countries:
        for kw in keywords:
            try:
                r = requests.get(
                    ENDPOINT_TMPL.format(country=country),
                    params={
                        "app_id": app_id,
                        "app_key": app_key,
                        "what": kw,
                        "max_days_old": max_days_old,
                        "results_per_page": results_per_keyword,
                        "sort_by": "date",
                    },
                    timeout=20,
                )
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                LOG.warning("adzuna fetch failed for %s/%s: %s", country, kw, e)
                continue

            for item in data.get("results", []):
                try:
                    posted = datetime.fromisoformat(item["created"].replace("Z", "+00:00"))
                except Exception:
                    posted = None
                if posted and posted < cutoff:
                    continue

                location = (item.get("location") or {}).get("display_name", "Unspecified")

                out.append(Job(
                    source=f"adzuna:{country}",
                    company=(item.get("company") or {}).get("display_name", "").strip(),
                    title=(item.get("title") or "").strip(),
                    location=location,
                    url=item.get("redirect_url", ""),
                    description=strip_html(item.get("description", "")),
                    posted_at=posted,
                    remote="remote" in location.lower(),
                    salary=(
                        f"{int(item['salary_min']):,}-{int(item['salary_max']):,}"
                        if item.get("salary_min") and item.get("salary_max") else ""
                    ),
                    external_id=str(item.get("id", "")),
                ))
    LOG.info("adzuna: %d jobs", len(out))
    return out
