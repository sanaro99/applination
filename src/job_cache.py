"""Disk-based job result cache to skip re-processing jobs seen in recent runs.

Cache key: Job.dedupe_key() (sha1 of company|title, first 16 chars).
Cache file: output/.job_cache.json (flat dict, one entry per key).
TTL: configurable, default 7 days. Expired entries are evicted on load.
"""
from __future__ import annotations
import json
import logging
from datetime import date, timedelta
from pathlib import Path

LOG = logging.getLogger(__name__)


class JobCache:
    def __init__(self, output_root: Path, ttl_days: int = 7, enabled: bool = True):
        self._path = Path(output_root) / ".job_cache.json"
        self._ttl = timedelta(days=max(0, ttl_days))
        self._enabled = enabled
        self._data: dict[str, dict] = {}
        if enabled:
            self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
                LOG.info("job_cache: loaded %d entries from %s", len(self._data), self._path)
            except Exception as e:
                LOG.warning("job_cache: failed to load (%s) -- starting empty", e)
                self._data = {}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except Exception as e:
            LOG.warning("job_cache: failed to save (%s)", e)

    def get(self, dedupe_key: str) -> dict | None:
        """Return cached result dict if within TTL, else None."""
        if not self._enabled:
            return None
        entry = self._data.get(dedupe_key)
        if not entry:
            return None
        try:
            cached_date = date.fromisoformat(entry["date"])
            if date.today() - cached_date <= self._ttl:
                return entry
        except (KeyError, ValueError):
            pass
        return None

    def put(self, dedupe_key: str, entry: dict) -> None:
        """Store result for a job. Saves to disk immediately."""
        if not self._enabled:
            return
        self._data[dedupe_key] = {**entry, "date": date.today().isoformat()}
        self._save()

    def evict_expired(self) -> int:
        """Remove entries older than TTL. Returns count of evicted entries."""
        if not self._enabled or not self._data:
            return 0
        cutoff = date.today() - self._ttl
        expired = [
            k for k, v in self._data.items()
            if date.fromisoformat(v.get("date", "2000-01-01")) < cutoff
        ]
        for k in expired:
            del self._data[k]
        if expired:
            self._save()
        return len(expired)
