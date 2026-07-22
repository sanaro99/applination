"""DeepSeek peak-hour pricing-window helper — single source of truth.

DeepSeek's 2025 off-peak *discount* ended 2025-09-05; V4 pricing is flat. The
mid-2026 V4 launch reportedly adds a peak-hour *surcharge* (~2x) during Beijing
business hours (09:00-12:00 & 14:00-18:00, UTC+8 => 01:00-04:00 & 06:00-10:00
UTC). That surcharge is UNCONFIRMED by DeepSeek's official docs, so the windows
are configurable and the whole behaviour can be disabled.

This module lets the run-trigger UI, the ``/api/pricing-window`` endpoint, and
the scheduler scripts all agree on "is now a peak-surcharge window" and "when
does the next non-peak slot start". Windows are UTC minutes-of-day; a window
whose start > end wraps past midnight.

Config (all optional)::

    pricing:
      avoid_peak: true
      peak_windows_utc:
        - "01:00-04:00"
        - "06:00-10:00"
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

# Beijing 09:00-12:00 & 14:00-18:00 (UTC+8) in UTC minutes-of-day.
DEFAULT_PEAK_WINDOWS_UTC: tuple[tuple[int, int], ...] = ((60, 240), (360, 600))


def _as_utc(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _parse_window(spec: str) -> tuple[int, int]:
    """Parse ``"HH:MM-HH:MM"`` into ``(start_min, end_min)`` UTC minutes."""
    start_s, end_s = spec.split("-")

    def to_min(t: str) -> int:
        h, m = t.strip().split(":")
        return int(h) * 60 + int(m)

    return to_min(start_s), to_min(end_s)


def load_windows(cfg: dict | None) -> tuple[bool, list[tuple[int, int]]]:
    """Return ``(avoid_peak, windows)`` from a loaded config dict.

    Falls back to the defaults if the ``pricing`` block is absent or malformed.
    """
    pricing = ((cfg or {}).get("pricing") or {})
    avoid_peak = bool(pricing.get("avoid_peak", True))
    raw = pricing.get("peak_windows_utc")
    if not raw:
        return avoid_peak, [tuple(w) for w in DEFAULT_PEAK_WINDOWS_UTC]
    windows: list[tuple[int, int]] = []
    for item in raw:
        try:
            windows.append(_parse_window(str(item)))
        except Exception:
            continue  # skip malformed entries rather than crash a run
    return avoid_peak, windows or [tuple(w) for w in DEFAULT_PEAK_WINDOWS_UTC]


def _in_window(minute: int, start: int, end: int) -> bool:
    if start <= end:
        return start <= minute < end
    return minute >= start or minute < end  # wraps past midnight


def is_peak(now: datetime | None = None, windows: list[tuple[int, int]] | None = None) -> bool:
    """True if ``now`` (default: current UTC) falls in any peak window."""
    now = _as_utc(now)
    windows = windows if windows is not None else [tuple(w) for w in DEFAULT_PEAK_WINDOWS_UTC]
    minute = now.hour * 60 + now.minute
    return any(_in_window(minute, s, e) for s, e in windows)


def next_non_peak(now: datetime | None = None, windows: list[tuple[int, int]] | None = None) -> datetime:
    """Earliest UTC datetime >= ``now`` that is not inside any peak window.

    Returns ``now`` unchanged when already clear; otherwise the end of the
    covering window, re-checking so back-to-back/adjacent windows are skipped.
    """
    cur = _as_utc(now)
    windows = windows if windows is not None else [tuple(w) for w in DEFAULT_PEAK_WINDOWS_UTC]
    if not windows:
        return cur
    for _ in range(len(windows) * 2 + 2):  # bounded; each hop clears one window
        minute = cur.hour * 60 + cur.minute
        covering = next(((s, e) for s, e in windows if _in_window(minute, s, e)), None)
        if covering is None:
            return cur
        _, end = covering
        end_dt = cur.replace(hour=(end // 60) % 24, minute=end % 60, second=0, microsecond=0)
        if end // 60 >= 24:  # end == 24:00 means midnight next day
            end_dt = end_dt.replace(hour=0) + timedelta(days=1)
        if end_dt <= cur:
            end_dt += timedelta(days=1)
        cur = end_dt
    return cur
