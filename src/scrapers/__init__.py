"""All scrapers return list[Job]. Main composes them."""
from .schema import Job, dedupe_key, utc_now, strip_html

__all__ = ["Job", "dedupe_key", "utc_now", "strip_html"]
