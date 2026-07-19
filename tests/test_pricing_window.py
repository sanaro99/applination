"""Unit tests for the DeepSeek peak-hour pricing-window helper."""
from datetime import datetime, timezone

from src.pricing_window import (
    DEFAULT_PEAK_WINDOWS_UTC,
    is_peak,
    load_windows,
    next_non_peak,
)


def _utc(h, m=0):
    return datetime(2026, 7, 18, h, m, tzinfo=timezone.utc)


def test_is_peak_boundaries_default_windows():
    # 01:00-04:00 and 06:00-10:00 UTC
    assert is_peak(_utc(0, 59)) is False   # before first window
    assert is_peak(_utc(1, 0)) is True     # start is inclusive
    assert is_peak(_utc(3, 59)) is True
    assert is_peak(_utc(4, 0)) is False    # end is exclusive
    assert is_peak(_utc(5, 0)) is False    # gap between windows
    assert is_peak(_utc(6, 0)) is True
    assert is_peak(_utc(9, 59)) is True
    assert is_peak(_utc(10, 0)) is False
    assert is_peak(_utc(20, 0)) is False


def test_next_non_peak_returns_now_when_clear():
    t = _utc(12, 0)
    assert next_non_peak(t) == t


def test_next_non_peak_jumps_to_window_end():
    assert next_non_peak(_utc(2, 30)) == _utc(4, 0)
    assert next_non_peak(_utc(6, 1)) == _utc(10, 0)


def test_next_non_peak_handles_adjacent_windows():
    # Two back-to-back windows should be skipped in one call.
    windows = [(60, 240), (240, 300)]  # 01:00-04:00 then 04:00-05:00
    assert next_non_peak(_utc(2, 0), windows) == _utc(5, 0)


def test_wrap_window_past_midnight():
    windows = [(1380, 60)]  # 23:00-01:00
    assert is_peak(_utc(23, 30), windows) is True
    assert is_peak(_utc(0, 30), windows) is True
    assert is_peak(_utc(1, 0), windows) is False
    # From 23:30 the next clear slot is 01:00 the following day.
    assert next_non_peak(_utc(23, 30), windows) == datetime(
        2026, 7, 19, 1, 0, tzinfo=timezone.utc
    )


def test_load_windows_defaults_and_parsing():
    avoid, windows = load_windows({})
    assert avoid is True
    assert windows == [tuple(w) for w in DEFAULT_PEAK_WINDOWS_UTC]

    avoid, windows = load_windows(
        {"pricing": {"avoid_peak": False, "peak_windows_utc": ["02:00-03:30"]}}
    )
    assert avoid is False
    assert windows == [(120, 210)]


def test_naive_datetime_treated_as_utc():
    naive = datetime(2026, 7, 18, 2, 0)  # no tzinfo
    assert is_peak(naive) is True
