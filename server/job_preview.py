"""Chapter 5: how many real jobs are out there for this person, right now.

``src.main.fetch_all`` is pure HTTP — no LLM anywhere — so this runs before the
user has a key, which is what makes the payoff possible at that point in the
journey. It is also slow (nine external services), so it runs on a daemon
thread and the client polls.

``matched`` is deterministic keyword overlap, not a ranking. Chapter 5 says
these postings "look like you", and what that honestly means is: the title or
description mentions something the user just told us.
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("server.job_preview")

CACHE_TTL_SECONDS = 30 * 60
SAMPLE_SIZE = 12

_lock = threading.Lock()
_state: dict[int, dict] = {}


def reset() -> None:
    """Drop all cached previews. For tests."""
    with _lock:
        _state.clear()


def _fetch(cfg: dict) -> tuple[list, int, int]:
    """Run the real scrapers. Returns (jobs, sources_ok, sources_total).

    Split out as a module-level function so tests can replace it without
    touching the threading or caching around it.
    """
    from src.main import fetch_all

    sources = cfg.get("sources") or {}
    total = sum(1 for v in sources.values() if isinstance(v, dict) and v.get("enabled"))
    jobs = fetch_all(cfg, log)
    # fetch_all swallows individual source failures, so a short result is the
    # only signal available. Report the enabled count as both until the scraper
    # layer reports per-source outcomes.
    return jobs, total, total


def _matches(job, keywords: list[str]) -> bool:
    haystack = f"{getattr(job, 'title', '')} {getattr(job, 'description', '')}".lower()
    return any(k.lower() in haystack for k in keywords)


def _worker(user_id: int, cfg: dict, keywords: list[str]) -> None:
    try:
        jobs, ok, total = _fetch(cfg)
    except Exception as exc:  # noqa: BLE001
        log.warning("job preview failed for user %s: %s", user_id, exc)
        with _lock:
            _state[user_id] = {
                "state": "error",
                "error": str(exc),
                "fetched_at": time.time(),
            }
        return

    matched = [j for j in jobs if _matches(j, keywords)] if keywords else []
    with _lock:
        _state[user_id] = {
            "state": "ready",
            "total": len(jobs),
            "matched": len(matched),
            "sources_ok": ok,
            "sources_total": total,
            "sample": [
                {
                    "title": getattr(j, "title", ""),
                    "company": getattr(j, "company", ""),
                    "location": getattr(j, "location", ""),
                    "url": getattr(j, "url", ""),
                }
                for j in matched[:SAMPLE_SIZE]
            ],
            "error": None,
            "fetched_at": time.time(),
        }


def start(user_id: int, cfg: dict, keywords: list[str]) -> None:
    """Kick off a preview unless one is running or a fresh one is cached."""
    with _lock:
        current = _state.get(user_id)
        if current:
            if current["state"] == "running":
                return
            if time.time() - current.get("fetched_at", 0) < CACHE_TTL_SECONDS:
                return
        _state[user_id] = {"state": "running", "fetched_at": time.time()}

    threading.Thread(
        target=_worker, args=(user_id, cfg, keywords), daemon=True
    ).start()


def status(user_id: int) -> dict:
    with _lock:
        current = _state.get(user_id)
    if not current:
        return {
            "state": "idle",
            "total": 0,
            "matched": 0,
            "sources_ok": 0,
            "sources_total": 0,
            "sample": [],
            "error": None,
        }
    return {
        "state": current["state"],
        "total": current.get("total", 0),
        "matched": current.get("matched", 0),
        "sources_ok": current.get("sources_ok", 0),
        "sources_total": current.get("sources_total", 0),
        "sample": current.get("sample", []),
        "error": current.get("error"),
    }
