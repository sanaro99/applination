"""Signed, revocable per-user tokens for the calendar feed.

``GET /api/calendar.ics`` has to be fetchable by Google Calendar, Apple
Calendar and friends, which send no cookies and cannot log in. PR 2 made it
session-only, which was safe but broke subscription entirely. PR 3 restores it
with a capability URL instead of a session.

Shape: ``<user_id>.<serial>.<signature>``, where the signature is an HMAC-SHA256
over ``calendar:<user_id>:<serial>`` keyed by ``APPLINATION_SECRET_KEY``. Two
properties matter:

* **Unguessable and unforgeable.** The old alternative — a bare
  ``/api/calendar.ics?user=7`` — would expose every user's interview schedule to
  anyone who could count.
* **Revocable without touching the key.** The serial lives in the user's
  ``Setting`` row; bumping it invalidates every previously issued URL for that
  one user and nobody else. Rotating the Fernet key would revoke everyone's.

The token grants exactly one thing: read access to that user's deadline and
interview feed. It is not a session and cannot be exchanged for one.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets

from .crypto import ENV_VAR
from .db import Setting, session

log = logging.getLogger("server.feed_tokens")

SERIAL_KEY = "calendar_feed_serial"


class FeedTokenUnavailable(RuntimeError):
    """No signing key configured, so tokens can be neither issued nor checked."""


def _signing_key() -> bytes:
    raw = (os.environ.get(ENV_VAR) or "").strip()
    if not raw:
        raise FeedTokenUnavailable(
            f"{ENV_VAR} is not set — calendar feed tokens cannot be issued"
        )
    # Hashed rather than used raw so the feed-signing key is not literally the
    # Fernet key: a token leak reveals nothing usable about the secret that
    # encrypts everyone's API keys.
    return hashlib.sha256(b"applination-feed:" + raw.encode()).digest()


def _sign(user_id: int, serial: str) -> str:
    msg = f"calendar:{user_id}:{serial}".encode()
    return hmac.new(_signing_key(), msg, hashlib.sha256).hexdigest()[:32]


def _get_serial(user_id: int) -> str | None:
    with session() as s:
        # noscope: Setting's primary key IS (user_id, key).
        row = s.get(Setting, (user_id, SERIAL_KEY))
        return row.value if row and row.value else None


def _set_serial(user_id: int, value: str) -> None:
    with session() as s:
        # noscope: composite primary key (user_id, key).
        row = s.get(Setting, (user_id, SERIAL_KEY))
        if row is None:
            row = Setting(user_id=user_id, key=SERIAL_KEY, value=value)
        else:
            row.value = value
        s.add(row)
        s.commit()


def issue_token(user_id: int, *, rotate: bool = False) -> str:
    """The user's current feed token, minting a serial on first use.

    ``rotate=True`` mints a fresh serial, which invalidates every URL handed out
    before — the disconnect path for a feed that ended up somewhere it should
    not have.
    """
    serial = None if rotate else _get_serial(user_id)
    if serial is None:
        serial = secrets.token_hex(8)
        _set_serial(user_id, serial)
    return f"{user_id}.{serial}.{_sign(user_id, serial)}"


def verify_token(token: str) -> int | None:
    """The user id this token authorises, or None.

    Returns None for every failure mode — malformed, unknown user, stale serial,
    bad signature — so a caller cannot tell them apart by probing.
    """
    if not token:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    raw_id, serial, sig = parts
    try:
        user_id = int(raw_id)
    except ValueError:
        return None

    try:
        expected = _sign(user_id, serial)
    except FeedTokenUnavailable:
        log.error("cannot verify a feed token: no %s configured", ENV_VAR)
        return None

    # Signature first, and in constant time: checking the serial before the
    # signature would let timing distinguish "valid signature, stale serial"
    # from "bad signature".
    if not hmac.compare_digest(expected, sig):
        return None
    current = _get_serial(user_id)
    if current is None or not hmac.compare_digest(current, serial):
        return None
    return user_id
