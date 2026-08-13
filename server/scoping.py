"""The single sanctioned way to touch a tenant table.

There are ~84 query sites across the routers. One of them missing a tenant
predicate is a cross-tenant data leak, and "remember to add `.where(...)`" is not
a control — it fails silently and only in production. So every read and write of
a tenant model goes through here, and ``tests/test_scope_lint.py`` fails the
build on any bare ``select()`` against a tenant model that is neither routed
through this module nor annotated ``# noscope: <reason>``.

**Ownership mismatches raise 404, never 403.** A 403 would confirm that the row
exists, turning any id-guessing loop into a census of other users' data. From
outside, another user's application is indistinguishable from one that was never
created.
"""
from __future__ import annotations

from typing import TypeVar

from fastapi import HTTPException
from sqlmodel import Session, SQLModel

from .db import TENANT_MODELS, User

M = TypeVar("M", bound=SQLModel)


def user_id_of(user: User | int) -> int:
    """Accept either a User (routers) or a bare id (the pipeline worker thread,
    which has no request and therefore no User object)."""
    return user if isinstance(user, int) else user.id  # type: ignore[return-value]


def _assert_tenant_model(model: type[SQLModel]) -> None:
    if model not in TENANT_MODELS:
        raise TypeError(
            f"{model.__name__} is not in db.TENANT_MODELS — scoping helpers are "
            "only meaningful for tenant tables. Add it there if it now carries "
            "user data, or query it directly with a `# noscope:` reason."
        )


def owned(stmt, model: type[SQLModel], user: User | int):
    """Append the tenant predicate to a select().

    Usage mirrors the unscoped form it replaces::

        rows = s.exec(owned(select(Application), Application, user)).all()
    """
    _assert_tenant_model(model)
    return stmt.where(model.user_id == user_id_of(user))  # type: ignore[attr-defined]


def get_owned(
    s: Session,
    model: type[SQLModel],
    obj_id,
    user: User | int,
    *,
    detail: str | None = None,
) -> M:
    """Fetch one row by primary key, 404ing unless the caller owns it.

    The not-found and not-yours cases deliberately produce the identical
    response.
    """
    _assert_tenant_model(model)
    obj = s.get(model, obj_id)
    if obj is None or obj.user_id != user_id_of(user):  # type: ignore[attr-defined]
        raise HTTPException(404, detail or f"{model.__name__.lower()} not found")
    return obj  # type: ignore[return-value]


def find_owned(
    s: Session,
    model: type[SQLModel],
    obj_id,
    user: User | int,
) -> M | None:
    """Like :func:`get_owned` but returns None instead of raising, for callers
    that treat a missing row as an ordinary branch rather than an error."""
    _assert_tenant_model(model)
    obj = s.get(model, obj_id)
    if obj is None or obj.user_id != user_id_of(user):  # type: ignore[attr-defined]
        return None
    return obj  # type: ignore[return-value]


def assert_owns(obj, user: User | int, *, detail: str | None = None) -> None:
    """Re-verify ownership of an already-loaded parent before inserting a child
    under it.

    ``user_id`` is denormalized onto child rows, so a child could otherwise be
    written with the caller's own user_id while pointing at another user's
    parent — consistent-looking and still a leak.
    """
    if obj is None or obj.user_id != user_id_of(user):
        raise HTTPException(404, detail or "not found")
