"""Optional, fail-open Redis cache for disposable operational data.

No caller may use this as a source of truth.  A cache outage must look like a
miss, because the service intentionally runs without Redis in local installs.
"""
from __future__ import annotations

from functools import lru_cache
import json
import logging
import os
from urllib.parse import quote

log = logging.getLogger("server.cache")


class Cache:
    def __init__(self) -> None:
        self._client = None
        self._warned = False
        url = (os.environ.get("REDIS_URL") or "").strip()
        if not url and os.environ.get("REDIS_PASSWORD"):
            password = quote(os.environ["REDIS_PASSWORD"], safe="")
            url = f"redis://:{password}@applination-redis:6379/0"
        if not url:
            return
        try:
            import redis

            self._client = redis.Redis.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=0.2,
                socket_timeout=0.2,
                health_check_interval=30,
            )
        except Exception as exc:  # pragma: no cover - optional dependency/runtime
            self._warn(exc)

    def _warn(self, exc: Exception) -> None:
        if not self._warned:
            log.warning("Redis cache unavailable; continuing without it: %s", str(exc)[:160])
            self._warned = True

    def get_json(self, key: str) -> dict | None:
        if self._client is None:
            return None
        try:
            raw = self._client.get(key)
            return json.loads(raw) if raw else None
        except Exception as exc:  # pragma: no cover - network failure path
            self._warn(exc)
            return None

    def set_json(self, key: str, value: dict, ttl_seconds: int) -> None:
        if self._client is None:
            return
        try:
            self._client.set(key, json.dumps(value, default=str), ex=ttl_seconds)
        except Exception as exc:  # pragma: no cover - network failure path
            self._warn(exc)


@lru_cache(maxsize=1)
def cache() -> Cache:
    return Cache()
