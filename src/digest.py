"""Build and send the daily application digest — stdlib only (smtplib).

The digest is a short morning email: deadlines coming up, interviews scheduled,
applications that have gone quiet (follow-up nudges), and fresh top matches from
the latest run. Sending reuses the inbox Gmail credentials over SMTP, so no
extra setup beyond the app password already used for inbox sync.

This module is pure presentation + transport; the server assembles the data.
"""
from __future__ import annotations
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage


@dataclass
class DigestData:
    deadlines: list[dict] = field(default_factory=list)     # {company,title,date,days_left,url}
    interviews: list[dict] = field(default_factory=list)    # {company,title,when,url}
    follow_ups: list[dict] = field(default_factory=list)    # {company,title,days_since,url}
    new_matches: list[dict] = field(default_factory=list)   # {company,title,score,url}
    counts: dict = field(default_factory=dict)              # status -> count

    @property
    def is_empty(self) -> bool:
        return not (
            self.deadlines or self.interviews or self.follow_ups or self.new_matches
        )


def _section_html(title: str, items: list[str]) -> str:
    if not items:
        return ""
    lis = "".join(f"<li style='margin:4px 0'>{it}</li>" for it in items)
    return (
        f"<h3 style='margin:18px 0 6px;font:600 15px system-ui'>{title}</h3>"
        f"<ul style='margin:0;padding-left:18px;font:14px system-ui;color:#222'>{lis}</ul>"
    )


def _link(text: str, url: str) -> str:
    if not url:
        return text
    return f"<a href='{url}' style='color:#4f46e5;text-decoration:none'>{text}</a>"


def build_digest(data: DigestData, *, name: str = "") -> tuple[str, str, str]:
    """Return (subject, html, text). HTML is inline-styled for email clients."""
    n_dead = len(data.deadlines)
    n_int = len(data.interviews)
    n_follow = len(data.follow_ups)
    bits = []
    if n_dead:
        bits.append(f"{n_dead} deadline{'s' if n_dead != 1 else ''}")
    if n_int:
        bits.append(f"{n_int} interview{'s' if n_int != 1 else ''}")
    if n_follow:
        bits.append(f"{n_follow} to follow up")
    subject = "Applination — " + (", ".join(bits) if bits else "your daily digest")

    # ---- HTML ----
    html_sections = []
    html_sections.append(_section_html(
        "⏰ Upcoming deadlines",
        [
            f"{_link(f'{d['company']} — {d['title']}', d.get('url',''))} "
            f"<span style='color:#b91c1c'>· {d['days_left']}d left ({d['date']})</span>"
            for d in data.deadlines
        ],
    ))
    html_sections.append(_section_html(
        "📅 Interviews",
        [
            f"{_link(f'{i['company']} — {i['title']}', i.get('url',''))} "
            f"<span style='color:#15803d'>· {i['when']}</span>"
            for i in data.interviews
        ],
    ))
    html_sections.append(_section_html(
        "📨 Quiet — consider a follow-up",
        [
            f"{_link(f'{f['company']} — {f['title']}', f.get('url',''))} "
            f"<span style='color:#a16207'>· applied {f['days_since']}d ago</span>"
            for f in data.follow_ups
        ],
    ))
    html_sections.append(_section_html(
        "✨ New top matches",
        [
            f"{_link(f'{m['company']} — {m['title']}', m.get('url',''))} "
            f"<span style='color:#666'>· score {m['score']}</span>"
            for m in data.new_matches
        ],
    ))
    counts_line = ""
    if data.counts:
        parts = " · ".join(f"{k}: {v}" for k, v in data.counts.items())
        counts_line = (
            f"<p style='margin:18px 0 0;font:12px system-ui;color:#888'>"
            f"Pipeline: {parts}</p>"
        )
    greeting = f"Morning{', ' + name if name else ''} —"
    body_html = "".join(s for s in html_sections if s) or (
        "<p style='font:14px system-ui;color:#444'>Nothing needs your attention "
        "today. 🎉</p>"
    )
    html = (
        "<div style='max-width:560px;margin:0 auto;padding:8px 4px'>"
        f"<p style='font:600 16px system-ui;color:#111'>{greeting}</p>"
        f"{body_html}{counts_line}"
        "<p style='margin:22px 0 0;font:11px system-ui;color:#aaa'>"
        "Sent by Applination · close-the-loop digest</p>"
        "</div>"
    )

    # ---- plain text ----
    lines = [greeting, ""]

    def _txt(title, items):
        if items:
            lines.append(title)
            lines.extend("  - " + it for it in items)
            lines.append("")

    _txt("Upcoming deadlines:", [
        f"{d['company']} — {d['title']} ({d['days_left']}d left, {d['date']})"
        for d in data.deadlines])
    _txt("Interviews:", [
        f"{i['company']} — {i['title']} ({i['when']})" for i in data.interviews])
    _txt("Follow up:", [
        f"{f['company']} — {f['title']} (applied {f['days_since']}d ago)"
        for f in data.follow_ups])
    _txt("New top matches:", [
        f"{m['company']} — {m['title']} (score {m['score']})"
        for m in data.new_matches])
    if data.is_empty:
        lines.append("Nothing needs your attention today.")
    text = "\n".join(lines).strip()

    return subject, html, text


def send_email(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    sender: str,
    to: str,
    subject: str,
    html: str,
    text: str,
) -> None:
    """Send a multipart email over SMTP+STARTTLS (Gmail-compatible)."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(text or "")
    msg.add_alternative(html or f"<pre>{text}</pre>", subtype="html")

    context = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls(context=context)
        server.login(username, password)
        server.send_message(msg)
