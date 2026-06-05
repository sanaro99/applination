"""Build an iCalendar (.ics) feed from application events — stdlib only.

No OAuth, no Google API: we emit a standards-compliant VCALENDAR that any
calendar app (Google Calendar import, Apple Calendar/Outlook subscription) can
read. The server exposes it at ``GET /api/calendar.ics``.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone


@dataclass
class CalEvent:
    uid: str
    summary: str
    start: datetime | date          # date => all-day
    end: datetime | date | None = None
    description: str = ""
    url: str = ""


def _escape(text: str) -> str:
    return (
        (text or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """Fold a content line at 75 octets per RFC 5545 (continuation = CRLF + space)."""
    if len(line.encode("utf-8")) <= 75:
        return line
    out, chunk, size = [], "", 0
    for ch in line:
        clen = len(ch.encode("utf-8"))
        if size + clen > 73:  # leave room for the leading space on continuation
            out.append(chunk)
            chunk, size = " " + ch, 1 + clen
        else:
            chunk += ch
            size += clen
    out.append(chunk)
    return "\r\n".join(out)


def _dt_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _date(d: date) -> str:
    return d.strftime("%Y%m%d")


def build_ics(events: list[CalEvent], calname: str = "Applination") -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Applination//Job Applications//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(calname)}",
    ]
    for ev in events:
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{ev.uid}")
        lines.append(f"DTSTAMP:{now}")
        # All-day when start is a plain date; timed when it's a datetime.
        if isinstance(ev.start, datetime):
            lines.append(f"DTSTART:{_dt_utc(ev.start)}")
            end = ev.end if isinstance(ev.end, datetime) else (
                ev.start + timedelta(hours=1)
            )
            lines.append(f"DTEND:{_dt_utc(end)}")
        else:
            lines.append(f"DTSTART;VALUE=DATE:{_date(ev.start)}")
            end_d = ev.end if isinstance(ev.end, date) and not isinstance(ev.end, datetime) else (
                ev.start + timedelta(days=1)
            )
            lines.append(f"DTEND;VALUE=DATE:{_date(end_d)}")
        lines.append(_fold(f"SUMMARY:{_escape(ev.summary)}"))
        if ev.description:
            lines.append(_fold(f"DESCRIPTION:{_escape(ev.description)}"))
        if ev.url:
            lines.append(_fold(f"URL:{_escape(ev.url)}"))
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
