"""Authentication: users, passwords, sessions, and the request dependencies.

Sessions are **server-side and opaque**. The cookie carries 32 random bytes;
only the SHA-256 of that token is stored. Two consequences worth keeping:

* Logout and password-change genuinely revoke — a stateless JWT could not,
  short of a denylist that is a session table wearing a disguise.
* A database leak does not hand out live sessions.

Password hashing is argon2id via ``argon2-cffi``, at its defaults.
"""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field as PField, field_validator
from sqlmodel import select

from .db import User, UserSession, session
from .limits import LOGIN_LIMIT, SIGNUP_LIMIT, limiter

log = logging.getLogger("server.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_NAME = "applination_session"
SESSION_TTL = timedelta(days=30)
# Refresh last_seen_at at most this often — every authenticated request would
# otherwise be a write.
_LAST_SEEN_INTERVAL = timedelta(minutes=5)

_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 12


# Deliberately loose. The address is only a login identifier — nothing is ever
# sent to it — so this exists to catch typos and obvious junk, not to decide
# deliverability. Pydantic's EmailStr would pull in email-validator for a
# stricter grammar that still cannot tell you whether an address is real.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: str) -> str:
    """Lowercase and strip. Applied on both signup and login so that
    ``Alice@Example.com`` cannot become a second account shadowing
    ``alice@example.com``."""
    return (email or "").strip().lower()


def valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email)) and len(email) <= 254


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
    return True


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(s, user_id: int) -> str:
    """Mint a session row and return the raw token (the only time it exists)."""
    token = secrets.token_urlsafe(32)
    s.add(UserSession(
        token_hash=_hash_token(token),
        user_id=user_id,
        expires_at=datetime.utcnow() + SESSION_TTL,
    ))
    s.commit()
    return token


def revoke_session(s, token: str) -> None:
    # noscope: UserSession is not a tenant table — it is keyed by the caller's
    # own opaque token, which is the authentication primitive itself.
    row = s.get(UserSession, _hash_token(token))
    if row is not None:
        s.delete(row)
        s.commit()


def revoke_all_sessions(s, user_id: int) -> int:
    """Drop every session for a user. Used on password change."""
    # noscope: UserSession is not a tenant table; this is already user-filtered.
    rows = s.exec(
        select(UserSession).where(UserSession.user_id == user_id)
    ).all()
    for r in rows:
        s.delete(r)
    s.commit()
    return len(rows)


def _set_cookie(response: Response, token: str, request: Request) -> None:
    # Secure is dropped only for plain-http origins so local development over
    # http://localhost works in browsers that do not treat it as a secure
    # context. Anything reached over https (i.e. production behind Traefik)
    # keeps it.
    secure = request.url.scheme == "https"
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
        max_age=int(SESSION_TTL.total_seconds()),
    )


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def resolve_user(request: Request) -> User | None:
    """Return the caller's user, or None. Never raises — the 401 is the
    dependency's and the middleware's job, so this can also be used by the
    middleware to decide."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    with session() as s:
        # noscope: UserSession/User lookups are the authentication path itself
        # and cannot be scoped to a user that has not been identified yet.
        row = s.get(UserSession, _hash_token(token))
        if row is None:
            return None
        now = datetime.utcnow()
        if row.expires_at <= now:
            s.delete(row)
            s.commit()
            return None
        user = s.get(User, row.user_id)
        if user is None or user.disabled:
            return None
        if now - row.last_seen_at > _LAST_SEEN_INTERVAL:
            row.last_seen_at = now
            s.add(row)
            s.commit()
        # Detached copy: the caller outlives this session.
        return User(**user.model_dump())


def require_user(request: Request) -> User:
    """FastAPI dependency: the authenticated user, or 401.

    Also stashes the id on ``request.state`` so the rate limiter can key on the
    user and the auth middleware can skip re-resolving.
    """
    user = resolve_user(request)
    if user is None:
        raise HTTPException(401, "not authenticated")
    request.state.user_id = user.id
    return user


# There is deliberately no `require_owner` any more. PR 2 needed one because
# config, master data and the provider keys were a single global that only the
# owner could safely touch; PR 3 made all three per-user, so every endpoint it
# guarded is now correct under plain `require_user`. Keeping a dead
# owner-gate around would invite the assumption that something is still
# owner-only. `User.is_owner` itself stays — it marks the account the CLI
# defaults to and the one the migration backfilled existing data onto.


class SignupBody(BaseModel):
    email: str
    password: str = PField(min_length=MIN_PASSWORD_LENGTH)

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        v = normalize_email(v)
        if not valid_email(v):
            raise ValueError("not a valid email address")
        return v


class LoginBody(BaseModel):
    # No format validation on login: a malformed address simply fails to match
    # any account, and rejecting it earlier with a different error would
    # distinguish "no such account" from "malformed".
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    is_owner: bool
    created_at: datetime


def _to_out(u: User) -> UserOut:
    return UserOut(
        id=u.id,  # type: ignore[arg-type]
        email=u.email,
        is_owner=u.is_owner,
        created_at=u.created_at,
    )


@router.post("/signup", response_model=UserOut)
@limiter.limit(SIGNUP_LIMIT)
def signup(request: Request, response: Response, body: SignupBody) -> UserOut:
    """Open signup — anyone can register. The risk is carried by rate limits and
    per-user caps rather than by an invite gate (a deliberate choice; see
    docs/MULTI-USER-PLAN.md)."""
    email = normalize_email(body.email)
    with session() as s:
        # noscope: User lookup during registration; no tenant context exists.
        existing = s.exec(select(User).where(User.email == email)).first()
        if existing is not None:
            # Deliberately the same shape of error as any other rejected signup
            # so this is not an account-enumeration oracle.
            raise HTTPException(409, "could not create that account")
        # The very first account to register becomes the owner. On an existing
        # install the migration has already created it, so this only fires on a
        # genuinely fresh database.
        first_user = s.exec(select(User)).first() is None
        user = User(
            email=email,
            password_hash=hash_password(body.password),
            is_owner=first_user,
        )
        s.add(user)
        s.commit()
        s.refresh(user)
        token = create_session(s, user.id)  # type: ignore[arg-type]
        out = _to_out(user)
    _set_cookie(response, token, request)
    log.info("user %s registered (owner=%s)", email, out.is_owner)
    return out


@router.post("/login", response_model=UserOut)
@limiter.limit(LOGIN_LIMIT)
def login(request: Request, response: Response, body: LoginBody) -> UserOut:
    email = normalize_email(body.email)
    with session() as s:
        # noscope: User lookup during authentication; no tenant context yet.
        user = s.exec(select(User).where(User.email == email)).first()
        # Verify even when there is no such user, so the response time does not
        # distinguish "no account" from "wrong password".
        ok = (
            verify_password(user.password_hash, body.password)
            if user is not None
            else verify_password(_DUMMY_HASH, body.password)
        )
        if user is None or not ok or user.disabled:
            raise HTTPException(401, "invalid email or password")
        token = create_session(s, user.id)  # type: ignore[arg-type]
        out = _to_out(user)
    _set_cookie(response, token, request)
    return out


# Hashed once at import so the no-such-user path does the same work as a real
# verify (timing-equalisation only; the value is never a valid password).
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(32))


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        with session() as s:
            revoke_session(s, token)
    _clear_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(require_user)) -> UserOut:
    return _to_out(user)


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str = PField(min_length=MIN_PASSWORD_LENGTH)


@router.post("/change-password")
def change_password(
    request: Request,
    response: Response,
    body: ChangePasswordBody,
    user: User = Depends(require_user),
) -> dict:
    """Change the password and revoke every session, including this one's
    siblings — the point of server-side sessions. The caller is re-issued a
    fresh cookie so they are not logged out of the tab they did it from."""
    with session() as s:
        # noscope: the caller's own User row, identified by the session.
        row = s.get(User, user.id)
        if row is None or not verify_password(row.password_hash, body.current_password):
            raise HTTPException(401, "current password is incorrect")
        row.password_hash = hash_password(body.new_password)
        s.add(row)
        s.commit()
        revoke_all_sessions(s, user.id)  # type: ignore[arg-type]
        token = create_session(s, user.id)  # type: ignore[arg-type]
    _set_cookie(response, token, request)
    return {"ok": True}
