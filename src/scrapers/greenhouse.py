"""
Greenhouse public job boards. Most tech companies use Greenhouse and expose
their boards at boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true.

No auth required; this is a public endpoint they intend to be consumed.
"""
from __future__ import annotations
import html as html_mod
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

import requests

from .schema import Job, strip_html
from .greenhouse_companies import BUILT_IN_SLUGS

LOG = logging.getLogger(__name__)
ENDPOINT_TMPL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
_MAX_WORKERS = 12


def _fetch_slug(slug: str, kws: list[str], cutoff: datetime) -> list[Job]:
    try:
        r = requests.get(
            ENDPOINT_TMPL.format(slug=slug),
            params={"content": "true"},
            timeout=20,
        )
        if r.status_code == 404:
            return []
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        LOG.debug("greenhouse: fetch failed for %s: %s", slug, e)
        return []

    jobs: list[Job] = []
    for item in data.get("jobs", []):
        title = (item.get("title") or "").strip()
        if not any(kw in title.lower() for kw in kws) and "intern" not in title.lower():
            continue

        try:
            posted = datetime.fromisoformat(item["updated_at"].replace("Z", "+00:00"))
        except Exception:
            posted = None
        if posted and posted < cutoff:
            continue

        location = (item.get("location") or {}).get("name", "Unspecified")
        content = html_mod.unescape(item.get("content") or "")

        jobs.append(Job(
            source=f"greenhouse:{slug}",
            company=slug.replace("-", " ").title(),
            title=title,
            location=location,
            url=item.get("absolute_url", ""),
            description=strip_html(content),
            posted_at=posted,
            remote="remote" in location.lower(),
            external_id=str(item.get("id", "")),
        ))
    return jobs


def fetch(
    extra_companies: list[str],
    keywords: list[str],
    last_n_hours: int = 24,
    use_builtin_list: bool = True,
) -> list[Job]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=last_n_hours)
    kws = [k.lower() for k in keywords]

    # Merge built-in list with any user-specified extras, preserving order, deduped.
    base = BUILT_IN_SLUGS if use_builtin_list else []
    all_slugs = list(dict.fromkeys(base + list(extra_companies)))

    out: list[Job] = []
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {pool.submit(_fetch_slug, slug, kws, cutoff): slug for slug in all_slugs}
        for fut in as_completed(futures):
            try:
                out.extend(fut.result())
            except Exception as e:
                LOG.debug("greenhouse: unexpected error for %s: %s", futures[fut], e)

    LOG.info("greenhouse: %d jobs across %d companies", len(out), len(all_slugs))
    return out
