"""User resolution for the command-line entrypoints.

``python -m src.main`` and ``python -m src.tweak`` are owner-operated tools —
they run on the host, not behind a session — but they still have to act *as*
some user now that config, master data and output are per-account. This is the
one place that turns a ``--user`` argument into a config and a set of paths, so
the CLI and the server read a user's data through exactly the same code (and
therefore get the same decrypted API keys).

Imported lazily from ``src/`` at call time, never at module import: ``src`` must
stay usable without a database, and the layering runs server -> src everywhere
else.
"""
from __future__ import annotations

from sqlmodel import select

from .db import User, session
from .deps import load_config, paths_for
from .user_paths import UserPaths


class UserNotFound(RuntimeError):
    """No account matched the --user argument."""


def resolve_user(spec: str | None = None) -> User:
    """Find the account to act as.

    ``spec`` is an email or a numeric id; ``None`` means the owner. Raises
    ``UserNotFound`` with a listing of real accounts rather than silently
    falling back to user 1 — running a full pipeline against the wrong person's
    resume is not a mistake worth being quiet about.
    """
    with session() as s:
        if spec is None or not str(spec).strip():
            # noscope: choosing which user to act as is the question being
            # answered here; there is no caller to scope to yet.
            user = s.exec(select(User).where(User.is_owner == True)).first()  # noqa: E712
            if user is None:
                # No owner on a fresh install — fall back to the lowest id so a
                # single-account setup works without anyone having to know that
                # `is_owner` exists.
                user = s.exec(select(User).order_by(User.id)).first()
            if user is None:
                raise UserNotFound(
                    "no accounts exist yet — sign up in the web app first"
                )
            return User(**user.model_dump())

        spec = str(spec).strip()
        # noscope: same — resolving which user to act as.
        if spec.isdigit():
            user = s.get(User, int(spec))
        else:
            user = s.exec(
                select(User).where(User.email == spec.lower())
            ).first()
        if user is None:
            # noscope: building the "did you mean" list for a CLI operator.
            known = [u.email for u in s.exec(select(User).order_by(User.id)).all()]
            raise UserNotFound(
                f"no account matching {spec!r}. Known accounts: "
                + (", ".join(known) if known else "(none)")
            )
        return User(**user.model_dump())


def context_for(spec: str | None = None) -> tuple[User, dict, UserPaths]:
    """``(user, config, paths)`` for a CLI run — config with secrets merged."""
    user = resolve_user(spec)
    return user, load_config(user), paths_for(user)
