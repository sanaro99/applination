"""Pricing-window endpoint — exposes DeepSeek peak-hour status to the web UI.

Single source of truth is ``src.pricing_window``; the run trigger uses this to
decide whether to offer "schedule after peak" and to render the status badge.
"""
from __future__ import annotations

from datetime import timezone

from fastapi import APIRouter

from .deps import load_config
from src.pricing_window import is_peak, load_windows, next_non_peak

router = APIRouter(prefix="/api", tags=["pricing"])


def _fmt(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


@router.get("/pricing-window")
def pricing_window() -> dict:
    cfg = load_config()
    avoid_peak, windows = load_windows(cfg)
    peak = is_peak(windows=windows) if avoid_peak else False
    nxt = next_non_peak(windows=windows).astimezone(timezone.utc)
    return {
        "avoid_peak": avoid_peak,
        "peak": peak,
        "next_non_peak_utc": nxt.isoformat().replace("+00:00", "Z"),
        "windows": [f"{_fmt(s)}-{_fmt(e)}" for s, e in windows],
    }
