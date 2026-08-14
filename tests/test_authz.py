"""Cross-tenant isolation: the acceptance bar for the multi-user work.

Two real users with real data, and for every tenant resource:

* A GET of B's object by id -> 404
* A mutation of B's object -> 404, **and B's row is unchanged**
* A's list endpoints never contain B's rows
* Unauthenticated -> 401
* Creating a child under B's parent -> 404

Plus the structural guards: every route is authenticated or explicitly public,
and each user's config, master data and documents are their own.

Ownership mismatches are asserted as **404, not 403** throughout. A 403 would
confirm the row exists, which turns id enumeration into a census of other users'
data.

Rows are seeded directly through the DB rather than through the generating
endpoints, because those endpoints run a real pipeline and call an LLM.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

import server.db as db
from server.db import (
    Application,
    ApplicationStatus,
    ChatMessage,
    ChatSession,
    RankedJob,
    Run,
    RunStatus,
    SavedAnswer,
    Setting,
)

from .conftest import PASSWORD, make_engine, register


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    """A migrated, isolated database with the app pointed at it."""
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, "engine", engine)
    from server.app import app

    return app


@pytest.fixture()
def users(app_env, tmp_path):
    """Users A and B, each with their own logged-in client and own data.

    A registers first and is therefore the owner (see auth.signup). Nothing is
    owner-gated any more, but B being a non-owner is what makes the "a plain
    account is a first-class tenant" assertions meaningful.
    """
    with TestClient(app_env) as ca, TestClient(app_env) as cb:
        a = register(ca, "a@example.com")
        b = register(cb, "b@example.com")
        data_a = _seed(a["id"], "Acme", tmp_path)
        data_b = _seed(b["id"], "Umbrella", tmp_path)
        yield {
            "a": {"client": ca, "user": a, "data": data_a},
            "b": {"client": cb, "user": b, "data": data_b},
        }


def _seed(user_id: int, company: str, tmp_path) -> dict:
    """One row in every tenant table, owned by ``user_id``."""
    folder = tmp_path / f"out_{company}"
    folder.mkdir(parents=True, exist_ok=True)

    with db.Session(db.engine) as s:
        run = Run(user_id=user_id, status=RunStatus.done, jobs_found=5)
        s.add(run)
        s.commit()
        s.refresh(run)

        app_row = Application(
            user_id=user_id,
            run_id=run.id,
            company=company,
            title="Engineer",
            folder_path=str(folder),
            folder_rel=f"day/{company}",
            match_score=77,
            status=ApplicationStatus.generated,
            notes="original",
            description="a job description",
            # A deadline and an interview so the calendar feed has content;
            # without them that assertion passes vacuously against an unscoped
            # implementation.
            deadline=datetime.utcnow() + timedelta(days=3),
            interview_at=datetime.utcnow() + timedelta(days=5),
        )
        s.add(app_row)
        s.commit()
        s.refresh(app_row)

        ranked = RankedJob(
            user_id=user_id,
            run_id=run.id,
            company=company,
            title="Engineer",
            description="desc",
            match_score=70,
        )
        s.add(ranked)

        sess = ChatSession(user_id=user_id, title=f"{company} chat")
        s.add(sess)
        s.commit()
        s.refresh(sess)

        msg = ChatMessage(
            user_id=user_id, session_id=sess.id, role="user", content="hello"
        )
        s.add(msg)

        ans = SavedAnswer(
            user_id=user_id, title=f"{company} answer", content="my answer"
        )
        s.add(ans)
        s.add(Setting(user_id=user_id, key="onboarded", value=company))
        s.commit()
        s.refresh(ranked)
        s.refresh(msg)
        s.refresh(ans)

        return {
            "run_id": run.id,
            "app_id": app_row.id,
            "ranked_id": ranked.id,
            "session_id": sess.id,
            "message_id": msg.id,
            "answer_id": ans.id,
            "company": company,
        }


# --------------------------------------------------------------------------- #
# Reads: A must never see B's rows
# --------------------------------------------------------------------------- #
def test_get_of_other_users_object_is_404(users):
    a, b = users["a"], users["b"]
    ca, bd = a["client"], b["data"]

    for path in (
        f"/api/applications/{bd['app_id']}",
        f"/api/runs/{bd['run_id']}",
        f"/api/runs/{bd['run_id']}/log",
        f"/api/chat/sessions/{bd['session_id']}",
    ):
        r = ca.get(path)
        assert r.status_code == 404, f"{path} -> {r.status_code} {r.text}"


def test_own_objects_are_reachable(users):
    """The 404s above have to be about ownership, not a broken route."""
    a = users["a"]
    ca, ad = a["client"], a["data"]

    assert ca.get(f"/api/applications/{ad['app_id']}").status_code == 200
    assert ca.get(f"/api/runs/{ad['run_id']}").status_code == 200
    assert ca.get(f"/api/chat/sessions/{ad['session_id']}").status_code == 200


def test_list_endpoints_never_contain_other_users_rows(users):
    a, b = users["a"], users["b"]
    ca = a["client"]
    b_company = b["data"]["company"]

    apps = ca.get("/api/applications").json()
    assert [x["id"] for x in apps] == [a["data"]["app_id"]]
    assert all(x["company"] != b_company for x in apps)

    runs = ca.get("/api/runs").json()
    assert [x["id"] for x in runs] == [a["data"]["run_id"]]

    sessions = ca.get("/api/chat/sessions").json()
    assert [x["id"] for x in sessions] == [a["data"]["session_id"]]

    answers = ca.get("/api/chat/answers").json()
    assert [x["id"] for x in answers] == [a["data"]["answer_id"]]

    ranked = ca.get(f"/api/runs/{a['data']['run_id']}/ranked").json()
    assert [x["id"] for x in ranked] == [a["data"]["ranked_id"]]

    # A's ranked list for B's run id must be empty, not B's pool.
    cross = ca.get(f"/api/runs/{b['data']['run_id']}/ranked").json()
    assert cross == []


def test_stats_only_counts_own_rows(users):
    """Aggregates leak just as effectively as row reads."""
    a = users["a"]
    stats = a["client"].get("/api/stats").json()
    assert stats["total_applications"] == 1
    assert [c["company"] for c in stats["top_companies"]] == [a["data"]["company"]]
    assert stats["runs_total"] == 1


def test_csv_export_only_contains_own_rows(users):
    a, b = users["a"], users["b"]
    body = a["client"].post("/api/applications/export", json={"ids": []}).text
    assert a["data"]["company"] in body
    assert b["data"]["company"] not in body


def _feed_path(client) -> str:
    r = client.get("/api/reminders/calendar-feed")
    assert r.status_code == 200, r.text
    return r.json()["path"]


def test_calendar_feed_only_contains_own_rows(users):
    a, b = users["a"], users["b"]
    text = a["client"].get(_feed_path(a["client"])).text
    # Assert the feed is non-empty first: otherwise "B's company is absent"
    # holds trivially and the test proves nothing.
    assert a["data"]["company"] in text
    assert b["data"]["company"] not in text


def test_calendar_feed_token_works_without_a_session(app_env, users):
    """The whole point: a subscribing calendar app sends no cookies."""
    a, b = users["a"], users["b"]
    path = _feed_path(a["client"])
    with TestClient(app_env) as anon:
        r = anon.get(path)
        assert r.status_code == 200
        assert a["data"]["company"] in r.text
        assert b["data"]["company"] not in r.text


def test_calendar_feed_rejects_a_missing_or_forged_token(app_env, users):
    path = _feed_path(users["a"]["client"])
    token = path.split("token=")[1]
    user_id, serial, sig = token.split(".")
    with TestClient(app_env) as anon:
        assert anon.get("/api/calendar.ics").status_code == 404
        assert anon.get("/api/calendar.ics?token=garbage").status_code == 404
        # Right shape, wrong signature.
        forged = f"{user_id}.{serial}.{'0' * len(sig)}"
        assert anon.get(f"/api/calendar.ics?token={forged}").status_code == 404
        # Another user's id under A's signature.
        swapped = f"{int(user_id) + 1}.{serial}.{sig}"
        assert anon.get(f"/api/calendar.ics?token={swapped}").status_code == 404


def test_rotating_the_calendar_token_revokes_the_old_url(app_env, users):
    ca = users["a"]["client"]
    old = _feed_path(ca)
    with TestClient(app_env) as anon:
        assert anon.get(old).status_code == 200
    new = ca.post("/api/reminders/calendar-feed/rotate").json()["path"]
    assert new != old
    with TestClient(app_env) as anon:
        assert anon.get(old).status_code == 404
        assert anon.get(new).status_code == 200


def test_one_users_token_does_not_rotate_anothers(users):
    """Revocation has to be per-user or it is a denial of service."""
    ca, cb = users["a"]["client"], users["b"]["client"]
    b_before = _feed_path(cb)
    ca.post("/api/reminders/calendar-feed/rotate")
    assert _feed_path(cb) == b_before


# --------------------------------------------------------------------------- #
# Mutations: 404 AND B's row unchanged
# --------------------------------------------------------------------------- #
def _application_row(app_id: int) -> Application:
    with db.Session(db.engine) as s:
        return s.get(Application, app_id)


def test_patch_of_other_users_application_is_404_and_changes_nothing(users):
    a, b = users["a"], users["b"]
    before = _application_row(b["data"]["app_id"])
    before_status, before_notes = before.status, before.notes

    r = a["client"].patch(
        f"/api/applications/{b['data']['app_id']}",
        json={"status": "rejected", "notes": "hacked"},
    )
    assert r.status_code == 404

    after = _application_row(b["data"]["app_id"])
    assert after.status == before_status
    assert after.notes == before_notes == "original"


def test_bulk_update_cannot_touch_other_users_rows(users):
    """The bulk path is the easy one to forget — it filters by id, not by id
    *and* owner, unless the scoping is applied."""
    a, b = users["a"], users["b"]
    b_app = b["data"]["app_id"]

    r = a["client"].post(
        "/api/applications/bulk",
        json={"ids": [a["data"]["app_id"], b_app], "status": "rejected"},
    )
    assert r.status_code == 200
    returned = {x["id"] for x in r.json()}
    assert b_app not in returned

    assert _application_row(b_app).status == ApplicationStatus.generated
    assert _application_row(a["data"]["app_id"]).status == ApplicationStatus.rejected


def test_dismiss_of_other_users_ranked_job_is_404_and_changes_nothing(users):
    a, b = users["a"], users["b"]
    r = a["client"].post(
        f"/api/ranked/{b['data']['ranked_id']}/dismiss", json={"dismissed": True}
    )
    assert r.status_code == 404
    with db.Session(db.engine) as s:
        assert s.get(RankedJob, b["data"]["ranked_id"]).dismissed is False


def test_patch_of_other_users_chat_session_is_404_and_changes_nothing(users):
    a, b = users["a"], users["b"]
    r = a["client"].patch(
        f"/api/chat/sessions/{b['data']['session_id']}", json={"title": "stolen"}
    )
    assert r.status_code == 404
    with db.Session(db.engine) as s:
        assert s.get(ChatSession, b["data"]["session_id"]).title.endswith("chat")


def test_delete_of_other_users_chat_session_is_404_and_deletes_nothing(users):
    a, b = users["a"], users["b"]
    r = a["client"].delete(f"/api/chat/sessions/{b['data']['session_id']}")
    assert r.status_code == 404
    with db.Session(db.engine) as s:
        assert s.get(ChatSession, b["data"]["session_id"]) is not None
        assert s.get(ChatMessage, b["data"]["message_id"]) is not None


def test_delete_of_other_users_saved_answer_is_404_and_deletes_nothing(users):
    a, b = users["a"], users["b"]
    r = a["client"].delete(f"/api/chat/answers/{b['data']['answer_id']}")
    assert r.status_code == 404
    with db.Session(db.engine) as s:
        assert s.get(SavedAnswer, b["data"]["answer_id"]) is not None


def test_stop_of_other_users_run_is_404(users):
    a, b = users["a"], users["b"]
    r = a["client"].post(f"/api/runs/{b['data']['run_id']}/stop", json={})
    assert r.status_code == 404


def test_compare_across_users_is_404(users):
    """Both ids must be owned — a mixed pair must not summarise B's run."""
    a, b = users["a"], users["b"]
    r = a["client"].get(
        f"/api/compare?a={a['data']['run_id']}&b={b['data']['run_id']}"
    )
    assert r.status_code == 404


def test_attach_answer_to_other_users_application_is_404(users):
    """This one writes a file into the application's folder, so an unscoped
    lookup would let A append text into B's answers.md."""
    a, b = users["a"], users["b"]
    r = a["client"].post(
        f"/api/chat/answers/{a['data']['answer_id']}/attach",
        json={"application_id": b["data"]["app_id"]},
    )
    assert r.status_code == 404
    assert not (
        _application_row(b["data"]["app_id"]).answers_file
    ), "B's application must not have gained an answers file"


def test_cover_letter_write_to_other_users_application_is_404(users):
    a, b = users["a"], users["b"]
    r = a["client"].put(
        f"/api/tweak/{b['data']['app_id']}/cover-letter",
        json={"text": "injected cover letter"},
    )
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Children created under another user's parent
# --------------------------------------------------------------------------- #
def test_creating_a_message_in_other_users_session_is_404(users):
    a, b = users["a"], users["b"]
    r = a["client"].post(
        f"/api/chat/sessions/{b['data']['session_id']}/messages",
        json={"content": "hello"},
    )
    assert r.status_code == 404
    with db.Session(db.engine) as s:
        from sqlmodel import select

        msgs = s.exec(
            select(ChatMessage).where(
                ChatMessage.session_id == b["data"]["session_id"]
            )
        ).all()
        assert len(msgs) == 1, "no message should have been added to B's session"


def test_creating_a_session_grounded_to_other_users_application_is_404(users):
    a, b = users["a"], users["b"]
    r = a["client"].post(
        "/api/chat/sessions", json={"application_id": b["data"]["app_id"]}
    )
    assert r.status_code == 404


def test_saving_an_answer_against_other_users_application_is_404(users):
    a, b = users["a"], users["b"]
    r = a["client"].post(
        "/api/chat/answers",
        json={"content": "x", "application_id": b["data"]["app_id"]},
    )
    assert r.status_code == 404


def test_saving_an_answer_citing_other_users_message_is_404(users):
    a, b = users["a"], users["b"]
    r = a["client"].post(
        "/api/chat/answers",
        json={"content": "x", "source_message_id": b["data"]["message_id"]},
    )
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Settings share a table but not a namespace
# --------------------------------------------------------------------------- #
def test_settings_are_per_user(users):
    """The Setting PK became (user_id, key). If it were still a bare key, these
    two rows could not coexist and one user's Gmail token would clobber the
    other's."""
    a, b = users["a"], users["b"]
    with db.Session(db.engine) as s:
        row_a = s.get(Setting, (a["user"]["id"], "onboarded"))
        row_b = s.get(Setting, (b["user"]["id"], "onboarded"))
    assert row_a.value == a["data"]["company"]
    assert row_b.value == b["data"]["company"]
    assert row_a.value != row_b.value


# --------------------------------------------------------------------------- #
# Unauthenticated
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/applications"),
        ("get", "/api/applications/1"),
        ("patch", "/api/applications/1"),
        ("post", "/api/applications/bulk"),
        ("get", "/api/runs"),
        ("post", "/api/runs"),
        ("get", "/api/stats"),
        ("get", "/api/chat/sessions"),
        ("post", "/api/chat/sessions"),
        ("get", "/api/chat/answers"),
        ("get", "/api/config"),
        ("put", "/api/config"),
        ("get", "/api/master-data/resume"),
        ("get", "/api/master-data/bio"),
        ("get", "/api/providers"),
        ("get", "/api/llm-config"),
        ("get", "/api/onboarding/status"),
        ("get", "/api/inbox/status"),
        ("get", "/api/auth/me"),
    ],
)
def test_unauthenticated_requests_are_401(app_env, method, path):
    with TestClient(app_env) as anon:
        r = _call(anon, method, path)
        assert r.status_code == 401, f"{method.upper()} {path} -> {r.status_code}"


def _call(client, method: str, path: str):
    """httpx's get/delete signatures take no ``json`` argument, so a body is
    only supplied for the methods that accept one."""
    if method in ("post", "put", "patch"):
        return getattr(client, method)(path, json={})
    return getattr(client, method)(path)


def test_files_endpoint_requires_authentication(app_env):
    """The StaticFiles mount is gone; /api/files is a real route behind auth."""
    with TestClient(app_env) as anon:
        assert anon.get("/api/files/anything.pdf").status_code == 401
        # And the old mount no longer serves anything at all.
        assert anon.get("/files/anything.pdf").status_code in (401, 404)


def test_public_paths_are_reachable_without_a_session(app_env):
    with TestClient(app_env) as anon:
        assert anon.get("/api/health").status_code == 200
        # Wrong credentials, but reached the handler rather than the middleware.
        assert anon.post(
            "/api/auth/login", json={"email": "nobody@example.com", "password": "x"}
        ).status_code == 401


# --------------------------------------------------------------------------- #
# Structural guards
# --------------------------------------------------------------------------- #
def test_every_route_is_protected_or_explicitly_public(app_env):
    """Layer 1 (the router dependency) fails open for a router added later
    without it. This enumerates the app's real routes and asserts each one is
    either authenticated or listed in PUBLIC_PATHS, so making something public
    has to be a deliberate edit."""
    from starlette.routing import Mount, Route

    from server.app import PUBLIC_PATHS

    unprotected: list[str] = []
    with TestClient(app_env) as anon:
        for route in app_env.routes:
            if isinstance(route, Mount):
                continue
            if not isinstance(route, Route):
                continue
            path = route.path
            if path in PUBLIC_PATHS:
                continue
            if "{" in path:
                # Substitute something concrete; auth is checked before the
                # handler ever looks at the value.
                path = _fill_params(route.path)
            method = _pick_method(route.methods or set())
            if method is None:
                continue
            r = _call(anon, method, path)
            if r.status_code != 401:
                unprotected.append(
                    f"{method.upper()} {route.path} -> {r.status_code}"
                )

    assert not unprotected, (
        "routes reachable without authentication and not in PUBLIC_PATHS:\n  "
        + "\n  ".join(unprotected)
    )


def _fill_params(path: str) -> str:
    import re

    return re.sub(r"\{[^}]+\}", "1", path)


def _pick_method(methods: set[str]) -> str | None:
    for m in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        if m in methods:
            return m.lower()
    return None


def test_route_enumeration_guard_catches_an_unprotected_route(app_env):
    """The enumeration above is only meaningful if it fails on a route that
    slipped through. Mount one deliberately and confirm it is caught."""
    from fastapi import APIRouter

    from server.app import PUBLIC_PATHS

    leaky = APIRouter()

    @leaky.get("/api/leaky-endpoint")
    def leaky_endpoint() -> dict:
        return {"secret": "everything"}

    app_env.include_router(leaky)  # deliberately WITHOUT the auth dependency
    try:
        with TestClient(app_env) as anon:
            r = anon.get("/api/leaky-endpoint")
        assert "/api/leaky-endpoint" not in PUBLIC_PATHS
        # The middleware (layer 2) must catch what the missing dependency
        # (layer 1) let through. If this ever returns 200, the second layer is
        # not doing its job and the enumeration test above is vacuous.
        assert r.status_code == 401, (
            "a router mounted without require_user was reachable — the "
            "fail-closed middleware is not working"
        )
    finally:
        app_env.router.routes = [
            r for r in app_env.router.routes
            if getattr(r, "path", None) != "/api/leaky-endpoint"
        ]


# --------------------------------------------------------------------------- #
# Config and master data (owner-gated in PR 2; per-user from PR 3)
#
# The owner gate is gone because the thing it protected is gone: there is no
# single global config.yaml left for a second account to reach. These tests
# assert the replacement — every account gets its own, and cannot see anybody
# else's.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/api/config", None),
        ("get", "/api/master-data/resume", None),
        ("get", "/api/master-data/stories", None),
        ("get", "/api/providers", None),
        ("get", "/api/llm-config", None),
        ("get", "/api/inbox/status", None),
        ("get", "/api/onboarding/status", None),
    ],
)
def test_non_owner_can_reach_their_own_config_endpoints(users, method, path, body):
    """A non-owner account is a first-class tenant now, not a second-class one."""
    cb = users["b"]["client"]
    assert users["b"]["user"]["is_owner"] is False
    kwargs = {"json": body} if body is not None else {}
    r = getattr(cb, method)(path, **kwargs)
    assert r.status_code == 200, f"{method.upper()} {path} -> {r.status_code}"


def test_config_is_not_shared_between_users(users):
    """The core of PR 3. B writing config must not be visible to A."""
    ca, cb = users["a"]["client"], users["b"]["client"]
    assert cb.put(
        "/api/config", json={"text": "user:\n  full_name: Only B\n"}
    ).status_code == 200
    assert "Only B" not in ca.get("/api/config").json()["text"]
    assert "Only B" in cb.get("/api/config").json()["text"]


def test_master_data_is_not_shared_between_users(users):
    ca, cb = users["a"]["client"], users["b"]["client"]
    assert cb.put(
        "/api/master-data/bio", json={"text": "B's private bio"}
    ).status_code == 200
    assert ca.get("/api/master-data/bio").json()["text"] == ""
    assert cb.get("/api/master-data/bio").json()["text"] == "B's private bio"


def test_stories_are_not_shared_between_users(users):
    ca, cb = users["a"]["client"], users["b"]["client"]
    cb.put("/api/master-data/stories/secret", json={"text": "---\ntags: []\n---\nB"})
    assert ca.get("/api/master-data/stories").json() == []
    assert [s["name"] for s in cb.get("/api/master-data/stories").json()] == ["secret"]
    # And not reachable by guessing the name either.
    assert ca.get("/api/master-data/stories/secret").status_code == 404


def test_api_keys_never_come_back_out_of_the_config_endpoint(users):
    """A key submitted through the raw YAML editor is stored encrypted and
    blanked in the file, so a later GET cannot hand it back — to its owner or
    to anyone who somehow reached the endpoint."""
    cb = users["b"]["client"]
    cb.put(
        "/api/config",
        json={"text": "llm:\n  deepseek:\n    api_key: sk-super-secret\n"},
    )
    assert "sk-super-secret" not in cb.get("/api/config").json()["text"]
    # But it is stored, and reported as set.
    status = cb.get("/api/secrets").json()
    assert status["key_configured"] is True
    names = [s["name"] for s in status["secrets"]]
    assert "llm.deepseek.api_key" in names
    # Masked, never the plaintext.
    entry = next(s for s in status["secrets"] if s["name"] == "llm.deepseek.api_key")
    assert entry["preview"] == "…cret"
    assert "sk-super-secret" not in str(status)


def test_stored_api_key_is_merged_back_for_the_owner_only(users):
    """The stored key has to reach the provider layer for its own user, and
    only for them — /api/providers reports it as configured for B, not A."""
    cb = users["b"]["client"]
    cb.put(
        "/api/config",
        json={"text": "llm:\n  deepseek:\n    api_key: sk-b-key\n    model: m\n"},
    )

    def deepseek_configured(client) -> bool:
        for p in client.get("/api/providers").json():
            if p["name"] == "deepseek":
                return p["configured"]
        return False

    assert deepseek_configured(cb) is True
    assert deepseek_configured(users["a"]["client"]) is False


def test_secrets_are_encrypted_at_rest(users):
    """The ciphertext in the database must not contain the key."""
    from server.db import UserSecret

    cb = users["b"]["client"]
    cb.put(
        "/api/config",
        json={"text": "llm:\n  mistral:\n    api_key: sk-plaintext-check\n"},
    )
    with db.Session(db.engine) as s:
        rows = s.exec(select(UserSecret)).all()
    assert rows, "nothing was stored"
    for row in rows:
        assert "sk-plaintext-check" not in row.ciphertext


# --------------------------------------------------------------------------- #
# Session mechanics
# --------------------------------------------------------------------------- #
def test_logout_revokes_the_session(app_env, tmp_path):
    with TestClient(app_env) as c:
        register(c, "logout@example.com")
        assert c.get("/api/auth/me").status_code == 200
        assert c.post("/api/auth/logout").status_code == 200
        assert c.get("/api/auth/me").status_code == 401


def test_password_change_revokes_other_sessions(app_env):
    """The point of server-side sessions: a stolen cookie dies when the password
    changes. The tab that changed it keeps working."""
    with TestClient(app_env) as first, TestClient(app_env) as second:
        register(first, "rotate@example.com")
        second.post(
            "/api/auth/login",
            json={"email": "rotate@example.com", "password": PASSWORD},
        )
        assert second.get("/api/auth/me").status_code == 200

        r = first.post(
            "/api/auth/change-password",
            json={
                "current_password": PASSWORD,
                "new_password": "a-brand-new-passphrase",
            },
        )
        assert r.status_code == 200
        assert second.get("/api/auth/me").status_code == 401
        assert first.get("/api/auth/me").status_code == 200


def test_signup_is_case_insensitive_on_email(app_env):
    """Otherwise Alice@x.com becomes a second account shadowing alice@x.com."""
    with TestClient(app_env) as c1, TestClient(app_env) as c2:
        register(c1, "Mixed.Case@Example.com")
        r = c2.post(
            "/api/auth/signup",
            json={"email": "mixed.case@example.com", "password": PASSWORD},
        )
        assert r.status_code == 409


def test_login_normalizes_email_case(app_env):
    with TestClient(app_env) as c1, TestClient(app_env) as c2:
        register(c1, "person@example.com")
        r = c2.post(
            "/api/auth/login",
            json={"email": "PERSON@Example.COM", "password": PASSWORD},
        )
        assert r.status_code == 200


def test_short_passwords_are_rejected(app_env):
    with TestClient(app_env) as c:
        r = c.post(
            "/api/auth/signup", json={"email": "short@example.com", "password": "abc"}
        )
        assert r.status_code == 422


def test_first_user_is_owner_and_second_is_not(app_env):
    with TestClient(app_env) as c1, TestClient(app_env) as c2:
        assert register(c1, "first@example.com")["is_owner"] is True
        assert register(c2, "second@example.com")["is_owner"] is False


def test_session_cookie_is_httponly(app_env):
    with TestClient(app_env) as c:
        r = c.post(
            "/api/auth/signup",
            json={"email": "cookie@example.com", "password": PASSWORD},
        )
        header = r.headers["set-cookie"].lower()
        assert "httponly" in header
        assert "samesite=lax" in header


def test_session_token_is_not_stored_in_plaintext(app_env):
    """A database leak must not hand out live sessions."""
    from sqlmodel import select

    from server.db import UserSession

    with TestClient(app_env) as c:
        c.post(
            "/api/auth/signup",
            json={"email": "hash@example.com", "password": PASSWORD},
        )
        raw = c.cookies.get("applination_session")

    with db.Session(db.engine) as s:
        rows = s.exec(select(UserSession)).all()
    assert len(rows) == 1
    assert rows[0].token_hash != raw
    import hashlib

    assert rows[0].token_hash == hashlib.sha256(raw.encode()).hexdigest()
