"""Fail the build on an unscoped query against a tenant table.

There are ~84 DB query sites across ``server/``. Every one of them needs a
tenant predicate, and one that does not is a cross-tenant data leak that no
functional test will notice — the endpoint keeps returning 200 with the right
shape, just with somebody else's rows in it.

So the rule is mechanical rather than remembered. A ``select(TenantModel)`` or
``s.get(TenantModel, ...)`` must either

* sit inside a call to ``owned()`` / ``get_owned()`` / ``find_owned()``
  (``server/scoping.py``), or
* carry a ``# noscope: <reason>`` comment within a few lines above it.

This is AST-based, not grep-based, so ``owned(select(X), ...)`` spanning several
lines is recognised and a ``select`` inside a string is not.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "server"

# Scoping wrappers. A query lexically inside one of these calls is scoped.
SCOPING_CALLS = {"owned", "get_owned", "find_owned"}

# How far above a query site a "# noscope:" comment may sit and still count.
# Small on purpose: it has to be obviously attached to the query it excuses.
NOSCOPE_WINDOW = 6


def _tenant_model_names() -> set[str]:
    from server.db import TENANT_MODELS

    return {m.__name__ for m in TENANT_MODELS}


def _iter_server_files():
    for path in sorted(SERVER.rglob("*.py")):
        # Migrations legitimately touch every table with raw SQL and predate
        # any notion of a request-scoped user.
        if "migrations" in path.parts:
            continue
        # scoping.py is the mechanism itself.
        if path.name == "scoping.py":
            continue
        yield path


def _noscope_lines(source: str) -> set[int]:
    return {
        i
        for i, line in enumerate(source.splitlines(), start=1)
        if "# noscope:" in line
    }


def _model_of(node: ast.AST, tenant: set[str]) -> str | None:
    """The tenant model a query node targets, if any.

    Handles ``select(Application)``, ``select(Application.company)`` and
    ``s.get(Application, id)``.
    """
    if not isinstance(node, ast.Call):
        return None

    func = node.func
    # select(...)
    if isinstance(func, ast.Name) and func.id == "select":
        for arg in node.args:
            name = _root_name(arg)
            if name in tenant:
                return name
        return None
    # <session>.get(Model, ...)
    if isinstance(func, ast.Attribute) and func.attr == "get" and node.args:
        name = _root_name(node.args[0])
        if name in tenant:
            return name
    return None


def _root_name(node: ast.AST) -> str | None:
    """`Application` from `Application` or `Application.company`."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _root_name(node.value)
    return None


def _scoped_ranges(tree: ast.AST) -> list[tuple[int, int]]:
    """Line spans covered by a scoping-helper call."""
    spans = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in SCOPING_CALLS
        ):
            spans.append((node.lineno, getattr(node, "end_lineno", node.lineno)))
    return spans


def _violations_in(path: Path, tenant: set[str]) -> list[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    spans = _scoped_ranges(tree)
    excused = _noscope_lines(source)
    try:
        rel = path.relative_to(ROOT).as_posix()
    except ValueError:
        # The self-check tests below lint a throwaway file under tmp_path.
        rel = path.as_posix()

    out: list[str] = []
    for node in ast.walk(tree):
        model = _model_of(node, tenant)
        if model is None:
            continue
        line = node.lineno
        if any(start <= line <= end for start, end in spans):
            continue
        if any(line - NOSCOPE_WINDOW <= n <= line for n in excused):
            continue
        out.append(f"{rel}:{line}: unscoped query against {model}")
    return out


def test_no_unscoped_tenant_queries():
    tenant = _tenant_model_names()
    violations: list[str] = []
    for path in _iter_server_files():
        violations.extend(_violations_in(path, tenant))
    assert not violations, (
        "Unscoped queries against tenant tables:\n  "
        + "\n  ".join(violations)
        + "\n\nRoute them through server/scoping.py (owned / get_owned / "
        "find_owned), or annotate with '# noscope: <reason>' if the query is "
        "deliberately cross-user."
    )


def test_lint_actually_catches_an_unscoped_query(tmp_path):
    """The guard above is only worth having if it fails on a real mistake.

    Without this, a bug in the AST walk would make the whole file silently
    vacuous — it would pass just as happily against a completely unscoped
    server.
    """
    bad = tmp_path / "bad_router.py"
    bad.write_text(
        "from sqlmodel import select\n"
        "from .db import Application\n"
        "def list_apps(s):\n"
        "    return s.exec(select(Application)).all()\n",
        encoding="utf-8",
    )
    found = _violations_in(bad, {"Application"})
    assert len(found) == 1, found
    assert "unscoped query against Application" in found[0]


def test_lint_accepts_scoped_and_annotated_forms(tmp_path):
    """...and does not fire on the two forms that are actually correct."""
    good = tmp_path / "good_router.py"
    good.write_text(
        "from sqlmodel import select\n"
        "from .db import Application\n"
        "from .scoping import owned\n"
        "def scoped(s, user):\n"
        "    return s.exec(owned(select(Application), Application, user)).all()\n"
        "def multiline(s, user):\n"
        "    return s.exec(\n"
        "        owned(\n"
        "            select(Application).where(Application.run_id == 1),\n"
        "            Application,\n"
        "            user,\n"
        "        )\n"
        "    ).all()\n"
        "def deliberate(s):\n"
        "    # noscope: background scheduler, dispatches across all users\n"
        "    return s.exec(select(Application)).all()\n",
        encoding="utf-8",
    )
    assert _violations_in(good, {"Application"}) == []


def test_every_tenant_model_is_registered():
    """A model with a user_id column that is missing from TENANT_MODELS would be
    invisible to both the scoping helpers and the lint above."""
    from sqlmodel import SQLModel

    from server.db import TENANT_MODELS

    registered = {m.__name__ for m in TENANT_MODELS}
    # Identity tables carry a user_id but are not tenant *data* — they are the
    # authentication substrate, and scoping them to a user is circular.
    exempt = {"UserSession", "UserSecret"}

    missing = set()
    for mapper_cls in SQLModel._sa_registry.mappers:
        cls = mapper_cls.class_
        if not hasattr(cls, "__tablename__"):
            continue
        cols = {c.name for c in cls.__table__.columns}
        if "user_id" in cols and cls.__name__ not in registered | exempt:
            missing.add(cls.__name__)

    assert not missing, (
        f"models carry user_id but are not in db.TENANT_MODELS: {sorted(missing)}"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
