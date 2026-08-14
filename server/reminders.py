"""Reminders — iCalendar feed + daily email digest.

- ``GET /api/calendar.ics`` serves a live feed of deadlines + interviews that a
  calendar app can import/subscribe to.
- The digest endpoints assemble "what needs attention" (deadlines, interviews,
  quiet applications to follow up, fresh matches) and email it through the
  Gmail API, reusing the same OAuth connection as inbox sync
  (``server/gmail_auth.py``).
"""
from __future__ import annotations
import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlmodel import select

from . import gmail_auth
from .auth import require_user
from .db import Application, ApplicationStatus, User, session
from .deps import load_config
from .feed_tokens import FeedTokenUnavailable, issue_token, verify_token
from .scoping import owned

router = APIRouter(tags=["reminders"])

# The calendar feed is mounted separately, *without* the require_user dependency
# every other router carries, because a calendar app cannot log in. It
# authenticates with a signed token instead (server/feed_tokens.py) and is
# listed in app.PUBLIC_PATHS so the middleware lets it through. That is the
# whole reason for the second router: nothing else here is public.
calendar_router = APIRouter(tags=["reminders"])
log = logging.getLogger("server.reminders")

_LIVE_STATES = (
    ApplicationStatus.generated,
    ApplicationStatus.applied,
    ApplicationStatus.interviewing,
    ApplicationStatus.offer,
)


def _reminders_cfg(user: User | int) -> dict:
    return (load_config(user).get("reminders") or {})


def _gather(user: User | int):
    """Collect digest/calendar data from the DB in one pass."""
    cfg = _reminders_cfg(user)
    window = int(cfg.get("deadline_window_days", 7) or 7)
    follow_up_days = int(cfg.get("follow_up_days", 10) or 10)
    now = datetime.utcnow()
    today = now.date()

    with session() as s:
        apps = s.exec(owned(select(Application), Application, user)).all()

    deadlines, interviews, follow_ups, new_matches = [], [], [], []
    counts: dict[str, int] = {}
    for a in apps:
        counts[a.status.value] = counts.get(a.status.value, 0) + 1
        live = a.status in _LIVE_STATES

        if live and a.deadline:
            days_left = (a.deadline.date() - today).days
            if 0 <= days_left <= window:
                deadlines.append({
                    "id": a.id, "company": a.company, "title": a.title,
                    "date": a.deadline.date().isoformat(), "days_left": days_left,
                    "url": a.url, "when": a.deadline,
                })
        if live and a.interview_at and a.interview_at >= now - timedelta(hours=12):
            interviews.append({
                "id": a.id, "company": a.company, "title": a.title,
                "when": a.interview_at.strftime("%a %b %d, %H:%M")
                if (a.interview_at.hour or a.interview_at.minute)
                else a.interview_at.strftime("%a %b %d"),
                "when_dt": a.interview_at, "url": a.url,
            })
        if a.status == ApplicationStatus.applied and not a.interview_at:
            ref = a.applied_at or a.created_at
            if ref:
                days_since = (now - ref).days
                if days_since >= follow_up_days:
                    follow_ups.append({
                        "id": a.id, "company": a.company, "title": a.title,
                        "days_since": days_since, "url": a.url,
                    })
        if a.status == ApplicationStatus.generated and a.created_at and \
                (now - a.created_at) <= timedelta(hours=36):
            new_matches.append({
                "id": a.id, "company": a.company, "title": a.title,
                "score": a.match_score, "url": a.url,
            })

    deadlines.sort(key=lambda d: d["days_left"])
    interviews.sort(key=lambda i: i["when_dt"])
    follow_ups.sort(key=lambda f: -f["days_since"])
    new_matches.sort(key=lambda m: -m["score"])
    new_matches = new_matches[:10]
    return deadlines, interviews, follow_ups, new_matches, counts


# --------------------------------------------------------------------------
# calendar feed
# --------------------------------------------------------------------------
@calendar_router.get("/api/calendar.ics")
def calendar_feed(token: str = "") -> Response:
    """Live iCalendar feed of one user's deadlines and interviews.

    Authenticated by a signed feed token rather than a session, because
    subscribing calendar apps send no cookies. An invalid or missing token is a
    flat 404: a 401 would tell a prober that some token shape is right, and
    there is nothing here to log into anyway.
    """
    from src.calendar_feed import build_ics, CalEvent

    try:
        user_id = verify_token(token)
    except FeedTokenUnavailable:
        user_id = None
    if user_id is None:
        raise HTTPException(404, "not found")

    deadlines, interviews, _follow, _new, _counts = _gather(user_id)
    events: list[CalEvent] = []
    for d in deadlines:
        events.append(CalEvent(
            uid=f"deadline-{d['id']}@applination",
            summary=f"Application deadline: {d['company']} — {d['title']}",
            start=date.fromisoformat(d["date"]),
            description=f"Apply to {d['title']} at {d['company']}.",
            url=d["url"],
        ))
    for i in interviews:
        dt = i["when_dt"]
        timed = bool(dt.hour or dt.minute)
        events.append(CalEvent(
            uid=f"interview-{i['id']}@applination",
            summary=f"Interview: {i['company']} — {i['title']}",
            start=dt if timed else dt.date(),
            description=f"Interview for {i['title']} at {i['company']}.",
            url=i["url"],
        ))
    ics = build_ics(events)
    return Response(
        content=ics,
        media_type="text/calendar",
        headers={"Content-Disposition": "inline; filename=applination.ics"},
    )


class CalendarFeedOut(BaseModel):
    path: str  # relative, so the browser can render it against its own origin


def _feed_out(user_id: int, *, rotate: bool = False) -> CalendarFeedOut:
    try:
        token = issue_token(user_id, rotate=rotate)
    except FeedTokenUnavailable as e:
        raise HTTPException(
            503,
            "Calendar subscription needs APPLINATION_SECRET_KEY to be set on "
            "the server.",
        ) from e
    return CalendarFeedOut(path=f"/api/calendar.ics?token={token}")


@router.get("/api/reminders/calendar-feed", response_model=CalendarFeedOut)
def calendar_feed_url(user: User = Depends(require_user)) -> CalendarFeedOut:
    """The subscribable URL for this user's feed, minted on first request."""
    return _feed_out(user.id)  # type: ignore[arg-type]


@router.post("/api/reminders/calendar-feed/rotate", response_model=CalendarFeedOut)
def rotate_calendar_feed(user: User = Depends(require_user)) -> CalendarFeedOut:
    """Invalidate every previously issued feed URL for this user and mint a new
    one — the fix for a link that ended up somewhere it should not have."""
    return _feed_out(user.id, rotate=True)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# digest
# --------------------------------------------------------------------------
def _build_digest_payload(user: User):
    from src.digest import DigestData, build_digest

    deadlines, interviews, follow_ups, new_matches, counts = _gather(user)
    data = DigestData(
        deadlines=deadlines, interviews=interviews, follow_ups=follow_ups,
        new_matches=new_matches, counts=counts,
    )
    # Renamed from `user`: that shadowed the User parameter this function now
    # takes, which would have silently passed a config dict to _gather().
    user_cfg = (load_config(user).get("user") or {})
    name = (user_cfg.get("full_name") or "").split(" ")[0]
    subject, html, text = build_digest(data, name=name)
    return data, subject, html, text


class DigestPreview(BaseModel):
    subject: str
    html: str
    text: str
    empty: bool


@router.get("/api/reminders/digest/preview", response_model=DigestPreview)
def digest_preview(user: User = Depends(require_user)) -> DigestPreview:
    data, subject, html, text = _build_digest_payload(user)
    return DigestPreview(subject=subject, html=html, text=text, empty=data.is_empty)


class DigestSendResult(BaseModel):
    sent: bool
    to: str


@router.post("/api/reminders/digest/send", response_model=DigestSendResult)
def digest_send(user: User = Depends(require_user)) -> DigestSendResult:
    from src.gmail_api import send_via_gmail_api

    cfg = load_config(user)
    rem = cfg.get("reminders") or {}
    creds = gmail_auth.get_credentials(user)
    sender = gmail_auth.account_email(user.id) or ""
    if creds is None or not sender:
        raise HTTPException(
            400,
            "Email sending needs Gmail connected — connect it from the Config page.",
        )
    to = str(rem.get("digest_to") or (cfg.get("user") or {}).get("email") or sender)
    _data, subject, html, text = _build_digest_payload(user)
    try:
        send_via_gmail_api(creds, sender=sender, to=to, subject=subject, html=html, text=text)
    except Exception as e:
        raise HTTPException(400, f"Gmail send failed: {e}")
    return DigestSendResult(sent=True, to=to)


@router.get("/api/reminders/status")
def reminders_status(user: User = Depends(require_user)) -> dict:
    rem = load_config(user).get("reminders") or {}
    # Each account has its own Gmail connection now, so this is simply whether
    # *this* user has connected one.
    can_send = gmail_auth.is_connected(user)
    deadlines, interviews, follow_ups, new_matches, _counts = _gather(user)
    return {
        "can_send_email": can_send,
        "digest_enabled": bool(rem.get("digest_enabled", False)),
        "counts": {
            "deadlines": len(deadlines),
            "interviews": len(interviews),
            "follow_ups": len(follow_ups),
            "new_matches": len(new_matches),
        },
    }
