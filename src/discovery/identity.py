"""Posting identities preserve source IDs and distinct requisitions."""
import hashlib
import json
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from src.scrapers.schema import Job


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith('utm_') and k.lower() not in {'ref', 'source'}]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip('/'), urlencode(sorted(query)), ''))


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def posting_key(job: Job) -> str:
    return digest([job.source, job.external_id or canonical_url(job.url)])


def fingerprint(job: Job) -> str:
    return digest([job.company, job.title, job.location, canonical_url(job.url), job.description,
                   job.remote, job.employment_type, job.posted_at])
