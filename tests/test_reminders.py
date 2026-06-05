"""Pure-function tests for the iCalendar feed + email digest builders."""
from __future__ import annotations
from datetime import date, datetime

from src.calendar_feed import CalEvent, build_ics
from src.digest import DigestData, build_digest


def test_ics_has_envelope_and_event():
    ics = build_ics([CalEvent(uid="x@1", summary="Deadline: Acme", start=date(2026, 6, 10))])
    assert ics.startswith("BEGIN:VCALENDAR")
    assert ics.rstrip().endswith("END:VCALENDAR")
    assert "BEGIN:VEVENT" in ics and "END:VEVENT" in ics
    assert ics.endswith("\r\n")  # CRLF line endings per RFC 5545


def test_ics_all_day_vs_timed():
    ics = build_ics([
        CalEvent(uid="d@1", summary="Deadline", start=date(2026, 6, 10)),
        CalEvent(uid="i@1", summary="Interview", start=datetime(2026, 6, 12, 14, 30)),
    ])
    assert "DTSTART;VALUE=DATE:20260610" in ics
    assert "DTSTART:20260612T" in ics  # timed event uses a full timestamp


def test_ics_escapes_special_chars():
    ics = build_ics([CalEvent(uid="x@1", summary="Acme, Inc; SWE", start=date(2026, 1, 1))])
    assert "Acme\\, Inc\\; SWE" in ics


def test_digest_subject_summarizes_counts():
    data = DigestData(
        deadlines=[{"company": "A", "title": "T", "date": "2026-06-10", "days_left": 5, "url": ""}],
        interviews=[{"company": "B", "title": "T", "when": "Fri", "url": ""}],
    )
    subject, html, text = build_digest(data, name="Sam")
    assert "1 deadline" in subject and "1 interview" in subject
    assert "Sam" in html
    assert "A" in text and "B" in text


def test_empty_digest_is_friendly():
    subject, html, text = build_digest(DigestData())
    assert "Nothing needs your attention" in text
    assert DigestData().is_empty is True
