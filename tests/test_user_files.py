"""Per-user document serving — the hole the old /files mount left open.

``app.mount("/files", StaticFiles(...))`` resolved a path on disk with no
ownership check anywhere in the request. Every test here would have failed
against it, which is the point: these are the assertions that make deleting it
safe.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server.db as db
from server.deps import output_root
from server.user_paths import PathEscape, UserPaths, resolve_within

from .conftest import make_engine, register


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, "engine", engine)
    from server.app import app

    return app


@pytest.fixture()
def two_users(app_env):
    """A and B, each with one document in their own output tree."""
    with TestClient(app_env) as ca, TestClient(app_env) as cb:
        a = register(ca, "a@example.com")
        b = register(cb, "b@example.com")
        for user, marker in ((a, "A-RESUME"), (b, "B-RESUME")):
            folder = output_root(user["id"]) / "2026-08-13" / "Acme_Engineer"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "resume.pdf").write_text(marker, encoding="utf-8")
        yield {"a": (ca, a), "b": (cb, b)}


_DOC = "/api/files/2026-08-13/Acme_Engineer/resume.pdf"


def test_each_user_gets_their_own_document_at_the_same_path(two_users):
    """The same URL, different files. Under the old shared mount both users
    read whichever one happened to be on disk."""
    ca, _ = two_users["a"]
    cb, _ = two_users["b"]
    assert ca.get(_DOC).text == "A-RESUME"
    assert cb.get(_DOC).text == "B-RESUME"


def test_a_cannot_reach_bs_tree_by_traversal_over_http(two_users):
    """The obvious attack over the wire: walk up out of your own root.

    Note what this does *not* prove. The URL layer normalises `..` away before
    routing, so these would 404 even with the endpoint's guard removed
    (verified by disabling it). It is a real defence-in-depth check, but
    `test_handler_rejects_traversal_that_bypasses_url_normalisation` below is
    the one that actually exercises the guard.
    """
    ca, _ = two_users["a"]
    _, b = two_users["b"]
    b_id = b["id"]
    for attack in (
        f"/api/files/../{b_id}/output/2026-08-13/Acme_Engineer/resume.pdf",
        f"/api/files/../../{b_id}/output/2026-08-13/Acme_Engineer/resume.pdf",
        f"/api/files/..%2f{b_id}%2foutput%2f2026-08-13%2fAcme_Engineer%2fresume.pdf",
        "/api/files/....//....//etc/passwd",
    ):
        r = ca.get(attack)
        assert r.status_code == 404, f"{attack} -> {r.status_code}"
        assert "B-RESUME" not in r.text


def test_handler_rejects_traversal_that_bypasses_url_normalisation(two_users):
    """Call the endpoint directly with a raw `..` path.

    Any proxy, rewrite, or client that hands the handler an unnormalised path
    puts it in exactly this position, so the guard cannot lean on the URL layer
    having cleaned up first. Removing the `is_relative_to` check in
    `resolve_within` makes this test read B's resume.
    """
    from fastapi import HTTPException

    from server.db import User
    from server.files import get_file

    _, a = two_users["a"]
    _, b = two_users["b"]
    a_user = User(id=a["id"], email=a["email"], password_hash="x")

    rel = f"../../{b['id']}/output/2026-08-13/Acme_Engineer/resume.pdf"
    with pytest.raises(HTTPException) as excinfo:
        get_file(rel, user=a_user)
    assert excinfo.value.status_code == 404

    # And the file it was aiming at really is readable by its owner, so the
    # rejection above is the guard working rather than a broken path.
    b_user = User(id=b["id"], email=b["email"], password_hash="x")
    resp = get_file("2026-08-13/Acme_Engineer/resume.pdf", user=b_user)
    assert resp.path.read_text(encoding="utf-8") == "B-RESUME"


def test_absolute_paths_do_not_escape(two_users):
    """`Path("/base") / "/etc/passwd"` discards the base entirely in pathlib —
    the containment check has to run after resolution, not before."""
    ca, _ = two_users["a"]
    for attack in ("/api/files//etc/passwd", "/api/files/C:/Windows/win.ini"):
        assert ca.get(attack).status_code == 404


def test_missing_file_is_404_not_500(two_users):
    ca, _ = two_users["a"]
    assert ca.get("/api/files/2026-08-13/Nope/resume.pdf").status_code == 404


def test_directories_are_not_served(two_users):
    """A directory resolves fine and stays inside the root — is_file() is what
    stops it being handed to FileResponse."""
    ca, _ = two_users["a"]
    assert ca.get("/api/files/2026-08-13").status_code == 404


def test_download_flag_sets_content_disposition(two_users):
    ca, _ = two_users["a"]
    inline = ca.get(_DOC)
    assert "attachment" not in inline.headers.get("content-disposition", "")
    attached = ca.get(_DOC + "?download=true")
    assert "attachment" in attached.headers["content-disposition"]


# --------------------------------------------------------------------------
# The primitives underneath
# --------------------------------------------------------------------------
def test_resolve_within_rejects_escapes(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    assert resolve_within(base, "a/b.txt") == (base / "a" / "b.txt").resolve()
    for bad in ("..", "../sibling", "a/../../sibling", "/etc/passwd"):
        with pytest.raises(PathEscape):
            resolve_within(base, bad)


def test_output_root_is_per_user_and_not_cached(app_env):
    """The old implementation was @lru_cache(maxsize=1), which would return
    user 1's directory to user 2 — every document written to, and served from,
    the wrong account's tree."""
    with TestClient(app_env) as ca, TestClient(app_env) as cb:
        a = register(ca, "a@example.com")
        b = register(cb, "b@example.com")
    root_a, root_b = output_root(a["id"]), output_root(b["id"])
    assert root_a != root_b
    # Interleaved calls must keep returning the right one.
    assert output_root(a["id"]) == root_a
    assert output_root(b["id"]) == root_b
    assert output_root(a["id"]) == root_a


def test_output_root_config_cannot_escape_the_user_directory(app_env):
    """output.root is user-editable through the raw YAML editor. An absolute
    path, or one climbing into another user's tree, must be ignored."""
    with TestClient(app_env) as ca:
        a = register(ca, "a@example.com")
    paths = UserPaths(user_id=a["id"]).ensure()

    for escape in ("/tmp/anywhere", "../2/output", "../../../etc"):
        assert paths.resolve_output({"output": {"root": escape}}) == \
            paths.default_output_dir

    # A legitimate relative subdirectory is still honoured.
    assert paths.resolve_output({"output": {"root": "docs"}}) == \
        (paths.root / "docs").resolve()
