# Structured Master-Data Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the raw-YAML textarea on `/master-data`'s resume tab with a section-based form, and make every edit — AI or human — reviewable before it is saved.

**Architecture:** The form speaks JSON to new structured endpoints; the server owns all YAML. `src/master_resume.py` gains a ruamel round-trip writer so saving never destroys comments or unmodelled keys. A new `server/master_data.py` router collects every master-data endpoint. The raw editor survives behind an `Advanced` sub-tab. Change review flattens both text and structured edits into a common `DiffLine[]` and renders them through one component.

**Tech Stack:** Python 3.14 / FastAPI / ruamel.yaml / jsonschema / pytest · Next.js 16 (App Router, Turbopack) / React / Tailwind v4 / shadcn (base-ui) / TanStack Query / @dnd-kit / vitest

**Spec:** `docs/superpowers/specs/2026-08-27-structured-master-data-editor-design.md`

## Global Constraints

- **Branch:** `feat/master-data-form` (already exists, spec committed). Do not push to `main` — it is protected and requires a PR.
- **No `Co-Authored-By: Claude` trailer on commits, and no Claude Code footer on PR bodies.**
- **Python is run through the venv:** `.venv/Scripts/python.exe -m pytest ...` on this Windows box. Plain `python` lacks the dependencies.
- **`src/` must never import from `server/`.** The pipeline is importable standalone; `PipelinePaths` is a Protocol for this reason.
- **Every tenant DB query goes through `server/scoping.py` or carries `# noscope: <reason>`** (`tests/test_scope_lint.py` enforces this). The endpoints in this plan touch no DB tables — they resolve files through `paths_for(user)` — so neither applies. Do not add a `# noscope:` marker where there is no query.
- **`MASTER_RESUME_SCHEMA` must not change.** It is the wire format for the LLM import.
- **The eight form-owned keys are exactly:** `profile`, `summary_options`, `core_skills`, `ats_adjacent_skills`, `skills`, `experience`, `projects`, `education`.
- **A key absent from submitted data is left alone, never deleted.** The form must not remove what it does not render.
- **`skills` is a mapping** (`{group_name: [items]}`), canonical since PR #57. Never reintroduce the `{group, items}` list on disk.
- **Frontend verification is `npm run build` + `npm run lint` + `npm run test`.** Do not attempt to verify visuals; the user checks those.
- **Copy rule:** user-facing labels name what the user controls, never the YAML key. "Jobs you've had", not "experience".

---

## File Structure

**Created**

| file | responsibility |
| --- | --- |
| `server/master_data.py` | every master-data endpoint (text + structured) |
| `tests/test_master_resume_render.py` | `render_master` round-trip behaviour |
| `tests/test_master_data_api.py` | structured GET/PUT, validation, auth |
| `web/lib/master-flatten.ts` | `flattenMaster` — master dict → labeled lines |
| `web/lib/master-flatten.test.ts` | diff/flatten edge cases |
| `web/vitest.config.ts` | vitest, scoped to `lib/**` |
| `web/components/change-review.tsx` | renders `DiffLine[]` with a count |
| `web/components/master-data/resume-form.tsx` | the form shell + save |
| `web/components/master-data/section-card.tsx` | collapsible section wrapper |
| `web/components/master-data/string-list.tsx` | reorderable list of text inputs |
| `web/components/master-data/section-identity.tsx` | `profile` |
| `web/components/master-data/section-summaries.tsx` | `summary_options` |
| `web/components/master-data/section-skills.tsx` | `core_skills`, `ats_adjacent_skills`, `skills` |
| `web/components/master-data/section-entries.tsx` | `experience`, `projects`, `education` |

**Modified**

| file | change |
| --- | --- |
| `src/master_resume.py` | add `FORM_KEYS`, `render_master` |
| `src/content_studio.py:25-28` | import `FORM_KEYS` instead of its own copy |
| `server/config_api.py` | master-data endpoints removed |
| `server/app.py:13-37,170-193` | register `master_data_router` |
| `web/lib/api.ts` | `MasterResume` types + two client methods |
| `web/components/text-editor.tsx` | change review replaces the amber text |
| `web/app/master-data/page.tsx` | thin tab router; resume tab gains Form/Advanced |
| `web/package.json` | vitest dev dependency + `test` script |

---

## Task 1: `render_master` — write YAML without destroying it

**Files:**
- Modify: `src/master_resume.py`
- Modify: `src/content_studio.py:25-28`
- Test: `tests/test_master_resume_render.py`

**Interfaces:**
- Consumes: `normalize_master` (exists in `src/master_resume.py` since PR #57)
- Produces: `FORM_KEYS: tuple[str, ...]`, `render_master(existing_text: str, data: dict) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_master_resume_render.py`:

```python
"""Saving the master resume must not damage what it did not touch.

The form owns eight top-level keys. Everything else in the file — comments a
user added through the Advanced tab, keys the schema does not model, the order
things appear in — belongs to the user, and a save that quietly discards any of
it is data loss in a file holding someone's career history.
"""
from __future__ import annotations

import yaml

from src.master_resume import FORM_KEYS, render_master

COMMENTED = """\
# My master resume. Notes to self below.
summary_options:
  - "Engineer"          # the one I actually use
core_skills:
  - "Python"
# Everything under here is mine, hands off.
private_notes: "call recruiter back"
"""


def test_the_eight_form_keys_are_exactly_what_the_form_owns():
    assert FORM_KEYS == (
        "profile",
        "summary_options",
        "core_skills",
        "ats_adjacent_skills",
        "skills",
        "experience",
        "projects",
        "education",
    )


def test_a_replaced_key_takes_the_new_value():
    out = render_master(COMMENTED, {"core_skills": ["Python", "Go"]})
    assert yaml.safe_load(out)["core_skills"] == ["Python", "Go"]


def test_comments_survive_a_save():
    out = render_master(COMMENTED, {"core_skills": ["Go"]})
    assert "# My master resume. Notes to self below." in out
    assert "# Everything under here is mine, hands off." in out


def test_a_key_the_schema_does_not_model_survives_a_save():
    out = render_master(COMMENTED, {"core_skills": ["Go"]})
    assert yaml.safe_load(out)["private_notes"] == "call recruiter back"


def test_a_key_absent_from_the_payload_is_left_alone_not_deleted():
    """The form renders a section at a time; omitting one must not erase it."""
    out = render_master(COMMENTED, {"core_skills": ["Go"]})
    assert yaml.safe_load(out)["summary_options"] == ["Engineer"]


def test_key_order_is_preserved():
    out = render_master(COMMENTED, {"core_skills": ["Go"]})
    assert list(yaml.safe_load(out)) == [
        "summary_options",
        "core_skills",
        "private_notes",
    ]


def test_skills_are_normalized_on_the_way_in():
    """A client that sends the old list shape must not put it back on disk."""
    out = render_master(
        "", {"skills": [{"group": "languages", "items": ["Python"]}]}
    )
    assert yaml.safe_load(out)["skills"] == {"languages": ["Python"]}


def test_an_empty_file_renders_a_whole_document():
    out = render_master("", {"core_skills": ["Python"]})
    assert yaml.safe_load(out) == {"core_skills": ["Python"]}


def test_a_long_bullet_is_not_rewrapped():
    """Rewrapping turns one bullet into a multi-line scalar, which shows up as a
    spurious change the next time the diff runs."""
    bullet = "Built " + "a very long thing " * 12
    out = render_master(
        "", {"experience": [{"company": "X", "role": "Y", "bullets_all": [bullet]}]}
    )
    assert yaml.safe_load(out)["experience"][0]["bullets_all"] == [bullet]
    assert bullet.strip() in out.replace("\n", " ")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_master_resume_render.py -q`
Expected: FAIL — `ImportError: cannot import name 'FORM_KEYS' from 'src.master_resume'`

- [ ] **Step 3: Implement `FORM_KEYS` and `render_master`**

Append to `src/master_resume.py`:

```python
# The top-level keys the structured editor owns. Anything else in the file —
# a comment, a key the schema does not model — belongs to the user and is
# copied through untouched.
FORM_KEYS: tuple[str, ...] = (
    "profile",
    "summary_options",
    "core_skills",
    "ats_adjacent_skills",
    "skills",
    "experience",
    "projects",
    "education",
)


def render_master(existing_text: str, data: dict) -> str:
    """Merge ``data`` into ``existing_text`` and return the YAML to write.

    Round-trips through ruamel rather than dumping a fresh document, so
    comments, key order and unmodelled keys survive. Only keys present in
    ``data`` are replaced: a section the caller omitted is left exactly as it
    was, because the form saves what it renders and must not erase what it
    does not.
    """
    from io import StringIO

    from ruamel.yaml import YAML
    from ruamel.yaml.comments import CommentedMap

    rt = YAML()
    rt.preserve_quotes = True
    # ruamel wraps at 80 by default, which would fold a long bullet into a
    # multi-line scalar and surface as a phantom change in the next diff.
    rt.width = 4096

    doc = rt.load(existing_text) if existing_text.strip() else None
    if not isinstance(doc, (dict, CommentedMap)):
        doc = CommentedMap()

    incoming = normalize_master(data)
    for key in FORM_KEYS:
        if key in incoming:
            doc[key] = incoming[key]

    buf = StringIO()
    rt.dump(doc, buf)
    return buf.getvalue()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_master_resume_render.py -q`
Expected: PASS (9 tests)

- [ ] **Step 5: Remove the duplicate key list from `content_studio`**

In `src/content_studio.py`, delete the `_MASTER_RESUME_KEYS` definition at lines 25-28 and import the shared one instead. Change the existing import line:

```python
from .master_resume import FORM_KEYS, normalize_skills
```

Then in `master_resume_to_yaml`, replace `_MASTER_RESUME_KEYS` with `FORM_KEYS`:

```python
    ordered = {k: data[k] for k in FORM_KEYS if k in data and data[k] not in (None, [], {})}
```

- [ ] **Step 6: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS, no fewer tests than before plus the 9 new ones

- [ ] **Step 7: Commit**

```bash
git add src/master_resume.py src/content_studio.py tests/test_master_resume_render.py
git commit -m "feat: render the master resume without destroying comments"
```

---

## Task 2: Collect master-data endpoints into their own router

A pure move. No URL changes, no behaviour changes — this is the structural step that keeps Task 3 from growing `config_api.py` into a third job.

**Files:**
- Create: `server/master_data.py`
- Modify: `server/config_api.py` (remove the moved handlers)
- Modify: `server/app.py`

**Interfaces:**
- Produces: `server.master_data.router` (an `APIRouter` with prefix `/api`)

- [ ] **Step 1: Write the failing test**

Create `tests/test_master_data_api.py`:

```python
"""The master-data endpoints, at their own door.

Every path here is per-user through ``paths_for``; there is no DB query and so
no scoping marker. The tests that matter are that the URLs did not move, that
one account cannot read another's file, and that the structured and text views
of the same file agree.
"""
from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient

import server.db as db
from server.user_paths import UserPaths

from .conftest import make_engine, register


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, "engine", engine)
    from server.app import app

    return app


@pytest.fixture()
def client(app_env):
    with TestClient(app_env) as c:
        register(c, "a@example.com")
        yield c


def test_the_router_is_registered_and_the_text_urls_did_not_move(client):
    assert client.get("/api/master-data/resume").status_code == 200
    assert client.get("/api/master-data/bio").status_code == 200
    assert client.get("/api/master-data/stories").status_code == 200


def test_the_text_put_still_writes(client):
    r = client.put(
        "/api/master-data/resume", json={"text": "core_skills:\n  - Python\n"}
    )
    assert r.status_code == 200, r.text
    on_disk = UserPaths(user_id=1).resume_path.read_text(encoding="utf-8")
    assert yaml.safe_load(on_disk)["core_skills"] == ["Python"]


def test_the_text_put_still_rejects_broken_yaml(client):
    r = client.put("/api/master-data/resume", json={"text": "a:\n  - b\n - c\n"})
    assert r.status_code == 400


def test_master_data_requires_a_session(app_env):
    with TestClient(app_env) as anon:
        assert anon.get("/api/master-data/resume").status_code == 401
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_master_data_api.py -q`
Expected: FAIL — no `tests/conftest.make_engine` import error; the failure is that the tests pass *only* if the endpoints still exist. Run it now and confirm PASS, which is the pre-move baseline. Record that it passes, then proceed: these tests must still pass after the move.

- [ ] **Step 3: Create the new router with the moved handlers**

Create `server/master_data.py`:

```python
"""Master-data endpoints — per-user, file-backed.

Split out of ``config_api.py``, which was serving two unrelated resources.
The URLs are unchanged. Nothing here touches a DB table: every path resolves
through ``paths_for(user)``, so ``server/scoping.py`` does not apply.

The text endpoints are deliberately permissive — they only check that the input
parses as YAML — because they back the Advanced editor, which is the escape
hatch for anything the structured schema does not model. The structured
endpoints in this same file are strict. Tolerant on read, strict on write.
"""
from __future__ import annotations
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import require_user
from .db import User
from .deps import paths_for
from .user_paths import UserPaths

router = APIRouter(prefix="/api/master-data", tags=["master-data"])


class TextBody(BaseModel):
    text: str


def _paths(user: User) -> UserPaths:
    return paths_for(user)


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _check_story_name(name: str) -> None:
    """Reject anything that could leave the user's stories directory.

    ``paths.ensure()`` creates the directory, but nothing else stops
    ``../../2/master_data`` from being appended to it.
    """
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(400, "invalid story name")


@router.get("/resume")
def get_resume(user: User = Depends(require_user)) -> dict:
    return {"text": _read(_paths(user).resume_path)}


@router.put("/resume")
def put_resume(body: TextBody, user: User = Depends(require_user)) -> dict:
    try:
        yaml.safe_load(body.text)
    except yaml.YAMLError as e:
        raise HTTPException(400, f"invalid YAML: {e}") from e
    _write(_paths(user).resume_path, body.text)
    return {"ok": True}


@router.get("/bio")
def get_bio(user: User = Depends(require_user)) -> dict:
    return {"text": _read(_paths(user).bio_path)}


@router.put("/bio")
def put_bio(body: TextBody, user: User = Depends(require_user)) -> dict:
    _write(_paths(user).bio_path, body.text)
    return {"ok": True}


@router.get("/stories")
def list_stories(user: User = Depends(require_user)) -> list[dict]:
    stories_dir = _paths(user).stories_dir
    if not stories_dir.exists():
        return []
    out: list[dict] = []
    for p in sorted(stories_dir.glob("*.md")):
        if p.name.startswith("_"):
            continue
        out.append({"name": p.stem, "size": p.stat().st_size})
    return out


@router.get("/stories/{name}")
def get_story(name: str, user: User = Depends(require_user)) -> dict:
    _check_story_name(name)
    p = _paths(user).stories_dir / f"{name}.md"
    if not p.exists():
        raise HTTPException(404, "story not found")
    return {"name": name, "text": _read(p)}


@router.put("/stories/{name}")
def put_story(name: str, body: TextBody, user: User = Depends(require_user)) -> dict:
    _check_story_name(name)
    _write(_paths(user).stories_dir / f"{name}.md", body.text)
    return {"ok": True}
```

Note the prefix is `/api/master-data`, so each route path drops that segment. The resulting URLs are identical to before.

- [ ] **Step 4: Remove the moved handlers from `config_api.py`**

Delete from `server/config_api.py`: `_check_story_name`, `_paths`, and every handler decorated with `@router.get("/master-data...")` or `@router.put("/master-data...")`. Keep `TextBody`, `_read`, `_write` — the config handlers still use them. Remove the now-unused `UserPaths` import if nothing else references it.

- [ ] **Step 5: Register the router in `server/app.py`**

Add the import beside the others (around line 21):

```python
from .master_data import router as master_data_router
```

Add `master_data_router,` to the `protected` tuple (around line 180), so it is mounted with `Depends(require_user)` like every other router.

- [ ] **Step 6: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS — the move is invisible to every existing test

- [ ] **Step 7: Commit**

```bash
git add server/master_data.py server/config_api.py server/app.py tests/test_master_data_api.py
git commit -m "refactor: give master data its own router"
```

---

## Task 3: `GET /api/master-data/resume/structured`

**Files:**
- Modify: `server/master_data.py`
- Test: `tests/test_master_data_api.py`

**Interfaces:**
- Consumes: `src.master_resume.load_master` (exists since PR #57)
- Produces: `GET /api/master-data/resume/structured` → `{"data": dict}`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_master_data_api.py`:

```python
def test_structured_get_returns_the_parsed_document(client):
    client.put(
        "/api/master-data/resume",
        json={"text": "core_skills:\n  - Python\nsummary_options:\n  - Engineer\n"},
    )
    r = client.get("/api/master-data/resume/structured")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["core_skills"] == ["Python"]


def test_structured_get_normalizes_the_old_skills_list(client):
    """Guards PR #57: a file written before the shape was settled must still
    load, not crash the form."""
    client.put(
        "/api/master-data/resume",
        json={"text": "skills:\n  - group: languages\n    items:\n      - Python\n"},
    )
    r = client.get("/api/master-data/resume/structured")
    assert r.json()["data"]["skills"] == {"languages": ["Python"]}


def test_structured_get_on_an_account_with_no_resume_is_empty_not_404(client):
    r = client.get("/api/master-data/resume/structured")
    assert r.status_code == 200
    assert r.json()["data"] == {}


def test_structured_get_requires_a_session(app_env):
    with TestClient(app_env) as anon:
        r = anon.get("/api/master-data/resume/structured")
        assert r.status_code == 401
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_master_data_api.py -q -k structured`
Expected: FAIL with 404 — the route does not exist

- [ ] **Step 3: Implement the endpoint**

Add the import at the top of `server/master_data.py`:

```python
from src.master_resume import load_master
```

Add the handler:

```python
@router.get("/resume/structured")
def get_resume_structured(user: User = Depends(require_user)) -> dict:
    """The resume as a dict, normalized.

    Tolerant by design: a half-finished or slightly wrong file still loads, so
    the form can render what is there instead of refusing to open. Strictness
    belongs on the way out, in PUT.
    """
    return {"data": load_master(_paths(user).resume_path)}
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_master_data_api.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/master_data.py tests/test_master_data_api.py
git commit -m "feat: serve the master resume as structured data"
```

---

## Task 4: `PUT /api/master-data/resume/structured` with usable validation errors

**Files:**
- Modify: `server/master_data.py`
- Test: `tests/test_master_data_api.py`

**Interfaces:**
- Consumes: `MASTER_RESUME_SCHEMA` from `src.schemas`, `render_master` and `FORM_KEYS` from `src.master_resume` (Task 1)
- Produces: `PUT /api/master-data/resume/structured` taking `{"data": dict}` → `{"ok": True}`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_master_data_api.py`:

```python
VALID = {
    "summary_options": ["Engineer"],
    "core_skills": ["Python"],
    "skills": {"languages": ["Python"]},
    "experience": [
        {"company": "X", "role": "Software Engineer", "bullets_all": ["Shipped a thing."]}
    ],
    "education": [{"school": "U", "degree": "BS CS"}],
}


def test_structured_put_writes_the_file(client):
    r = client.put("/api/master-data/resume/structured", json={"data": VALID})
    assert r.status_code == 200, r.text
    on_disk = yaml.safe_load(
        UserPaths(user_id=1).resume_path.read_text(encoding="utf-8")
    )
    assert on_disk["core_skills"] == ["Python"]
    assert on_disk["skills"] == {"languages": ["Python"]}


def test_a_no_op_save_neither_reorders_nor_drops_keys(client):
    client.put("/api/master-data/resume/structured", json={"data": VALID})
    first = client.get("/api/master-data/resume/structured").json()["data"]
    client.put("/api/master-data/resume/structured", json={"data": first})
    second = client.get("/api/master-data/resume/structured").json()["data"]
    assert second == first
    assert list(second) == list(first)


def test_structured_put_preserves_a_comment_added_through_the_text_editor(client):
    client.put(
        "/api/master-data/resume",
        json={"text": "# hands off\ncore_skills:\n  - Python\nprivate: yes\n"},
    )
    client.put("/api/master-data/resume/structured", json={"data": VALID})
    on_disk = UserPaths(user_id=1).resume_path.read_text(encoding="utf-8")
    assert "# hands off" in on_disk
    assert yaml.safe_load(on_disk)["private"] is True


def test_a_missing_required_field_is_rejected_by_name(client):
    broken = {
        **VALID,
        "experience": [{"role": "Software Engineer", "bullets_all": ["x"]}],
    }
    r = client.put("/api/master-data/resume/structured", json={"data": broken})
    assert r.status_code == 400
    assert "experience[0]" in r.json()["detail"]
    assert "company" in r.json()["detail"]


def test_a_wrong_type_is_rejected_by_path(client):
    broken = {**VALID, "core_skills": "Python"}
    r = client.put("/api/master-data/resume/structured", json={"data": broken})
    assert r.status_code == 400
    assert "core_skills" in r.json()["detail"]


def test_a_rejected_save_does_not_touch_the_file(client):
    client.put("/api/master-data/resume", json={"text": "core_skills:\n  - Original\n"})
    client.put(
        "/api/master-data/resume/structured",
        json={"data": {**VALID, "core_skills": "not a list"}},
    )
    on_disk = yaml.safe_load(
        UserPaths(user_id=1).resume_path.read_text(encoding="utf-8")
    )
    assert on_disk["core_skills"] == ["Original"]


def test_structured_and_text_views_agree_on_the_same_file(client):
    client.put("/api/master-data/resume/structured", json={"data": VALID})
    text = client.get("/api/master-data/resume").json()["text"]
    structured = client.get("/api/master-data/resume/structured").json()["data"]
    assert yaml.safe_load(text)["core_skills"] == structured["core_skills"]


def test_structured_put_requires_a_session(app_env):
    with TestClient(app_env) as anon:
        r = anon.put("/api/master-data/resume/structured", json={"data": VALID})
        assert r.status_code == 401
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_master_data_api.py -q -k "put or agree or no_op"`
Expected: FAIL with 405 or 404 — the route does not exist

- [ ] **Step 3: Implement validation and the endpoint**

Add imports to `server/master_data.py`:

```python
import re

from jsonschema import Draft202012Validator

from src.master_resume import FORM_KEYS, load_master, render_master
from src.schemas import MASTER_RESUME_SCHEMA
```

Add the body model beside `TextBody`:

```python
class StructuredBody(BaseModel):
    data: dict
```

Add the error translator and the handler:

```python
def _field_path(error) -> str:
    """Turn a jsonschema error path into something a person can act on.

    ``deque(['experience', 1, 'company'])`` becomes ``experience[1].company``.
    The raw validator message names a JSON pointer and a schema fragment, which
    is not usable by the audience this editor exists for.
    """
    parts: list[str] = []
    for step in error.absolute_path:
        if isinstance(step, int):
            if parts:
                parts[-1] = f"{parts[-1]}[{step}]"
            else:
                parts.append(f"[{step}]")
        else:
            parts.append(str(step))
    return ".".join(parts)


def _validation_detail(error) -> str:
    where = _field_path(error)
    if error.validator == "required":
        match = re.search(r"'([^']+)'", error.message)
        field = match.group(1) if match else "a required field"
        return f"{where}.{field} is required" if where else f"{field} is required"
    return f"{where or 'the document'}: {error.message}"


@router.put("/resume/structured")
def put_resume_structured(
    body: StructuredBody, user: User = Depends(require_user)
) -> dict:
    """Validate, then merge into the file the user already has.

    Validation runs before any write, so a rejected save leaves the previous
    resume exactly as it was. Only the keys present in ``data`` are replaced —
    ``render_master`` leaves the rest, including anything the schema does not
    model.
    """
    payload = {k: v for k, v in body.data.items() if k in FORM_KEYS}

    errors = sorted(
        Draft202012Validator(MASTER_RESUME_SCHEMA).iter_errors(_for_schema(payload)),
        key=lambda e: list(e.absolute_path),
    )
    if errors:
        raise HTTPException(400, "; ".join(_validation_detail(e) for e in errors[:3]))

    path = _paths(user).resume_path
    _write(path, render_master(_read(path), payload))
    return {"ok": True}
```

**The `skills` shapes do not match, and this is verified, not hypothetical.**
`MASTER_RESUME_SCHEMA` declares `skills` as an array of `{group, items}`; the
canonical on-disk shape is a mapping (PR #57). Validating a mapping against the
schema fails with `{'languages': [...]} is not of type 'array'`.

`MASTER_RESUME_SCHEMA` must not change — it is the LLM wire format. So convert a
copy for validation only, and write the mapping. Add this helper above the
handler:

```python
def _for_schema(payload: dict) -> dict:
    """A copy shaped the way MASTER_RESUME_SCHEMA expects.

    The schema wants ``skills`` as a {group, items} list because structured
    output is more reliable with fixed keys. Disk wants the mapping, because a
    person has to read it. Neither is wrong; they just answer to different
    readers, so the conversion lives here and nowhere else.
    """
    if not isinstance(payload.get("skills"), dict):
        return payload
    return {
        **payload,
        "skills": [
            {"group": group, "items": items}
            for group, items in payload["skills"].items()
        ],
    }
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_master_data_api.py -q`
Expected: PASS

- [ ] **Step 4b: Pin the shape conversion with its own test**

Append to `tests/test_master_data_api.py`:

```python
def test_mapping_shaped_skills_are_accepted_even_though_the_schema_wants_a_list(client):
    """The schema and the disk format disagree about `skills` on purpose. If
    this fails, someone has "fixed" one of the two shapes and broken the other."""
    r = client.put(
        "/api/master-data/resume/structured",
        json={"data": {**VALID, "skills": {"languages": ["Python"], "data": ["SQL"]}}},
    )
    assert r.status_code == 200, r.text
    on_disk = yaml.safe_load(
        UserPaths(user_id=1).resume_path.read_text(encoding="utf-8")
    )
    assert on_disk["skills"] == {"languages": ["Python"], "data": ["SQL"]}
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_master_data_api.py -q`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add server/master_data.py tests/test_master_data_api.py
git commit -m "feat: accept structured master resume saves with named field errors"
```

---

## Task 5: vitest, and `flattenMaster`

**Files:**
- Create: `web/vitest.config.ts`
- Create: `web/lib/master-flatten.ts`
- Create: `web/lib/master-flatten.test.ts`
- Modify: `web/package.json`

**Interfaces:**
- Consumes: `DiffLine`, `diffLines` from `web/lib/resume-diff.ts` (both already exported)
- Produces: `flattenMaster(data: MasterResume): string[]`

- [ ] **Step 1: Install vitest and add the script**

```bash
cd web && npm install -D vitest@^3
```

In `web/package.json`, add to `scripts`:

```json
    "test": "vitest run"
```

- [ ] **Step 2: Add the config**

Create `web/vitest.config.ts`:

```ts
import { defineConfig } from "vitest/config";

// Scoped to pure functions in lib/ on purpose. Components and visuals are
// verified by build + lint and by the user looking at them; what needs a test
// here is logic whose failure mode is showing someone a false account of their
// own changes.
export default defineConfig({
  test: {
    include: ["lib/**/*.test.ts"],
    environment: "node",
  },
});
```

- [ ] **Step 3: Write the failing tests**

Create `web/lib/master-flatten.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { diffLines } from "./resume-diff";
import { flattenMaster } from "./master-flatten";

const BASE = {
  summary_options: ["Engineer who ships"],
  core_skills: ["Python", "SQL"],
  skills: { languages: ["Python"] },
  experience: [
    {
      company: "Example Corp",
      role: "Software Engineer",
      bullets_all: ["Built the thing", "Owned the release"],
    },
  ],
  education: [{ school: "State University", degree: "BS CS" }],
};

const changes = (a: object, b: object) =>
  diffLines(flattenMaster(a), flattenMaster(b)).filter((l) => l.type !== "same");

describe("flattenMaster", () => {
  it("labels a job with its role and company", () => {
    expect(flattenMaster(BASE)).toContain(
      "§ Jobs — Software Engineer @ Example Corp",
    );
  });

  it("renders each bullet as its own line", () => {
    expect(flattenMaster(BASE)).toContain("• Built the thing");
    expect(flattenMaster(BASE)).toContain("• Owned the release");
  });

  it("survives an empty document", () => {
    expect(flattenMaster({})).toEqual([]);
  });
});

describe("diffing a flattened master resume", () => {
  it("reports no changes for an identical document", () => {
    expect(changes(BASE, BASE)).toEqual([]);
  });

  it("reports a bullet removed from the middle as one removal", () => {
    const after = {
      ...BASE,
      experience: [{ ...BASE.experience[0], bullets_all: ["Owned the release"] }],
    };
    const diff = changes(BASE, after);
    expect(diff).toHaveLength(1);
    expect(diff[0]).toEqual({ type: "remove", text: "• Built the thing" });
  });

  it("reports an edited bullet as one removal and one addition", () => {
    const after = {
      ...BASE,
      experience: [
        {
          ...BASE.experience[0],
          bullets_all: ["Built the thing faster", "Owned the release"],
        },
      ],
    };
    const diff = changes(BASE, after);
    expect(diff.filter((l) => l.type === "remove")).toHaveLength(1);
    expect(diff.filter((l) => l.type === "add")).toHaveLength(1);
  });

  it("reports an emptied section as removals, not a crash", () => {
    const diff = changes(BASE, { ...BASE, core_skills: [] });
    expect(diff.every((l) => l.type === "remove")).toBe(true);
    expect(diff.length).toBeGreaterThan(0);
  });

  it("reports a reordered pair of bullets as exactly one move's worth of noise", () => {
    // A line diff cannot express a move: it shows one side removed and re-added.
    // Pinned so improving it later is a deliberate change, not a surprise.
    const after = {
      ...BASE,
      experience: [
        {
          ...BASE.experience[0],
          bullets_all: ["Owned the release", "Built the thing"],
        },
      ],
    };
    const diff = changes(BASE, after);
    expect(diff).toHaveLength(2);
    expect(diff.map((l) => l.type).sort()).toEqual(["add", "remove"]);
  });
});
```

- [ ] **Step 4: Run to verify they fail**

Run: `cd web && npm run test`
Expected: FAIL — `Failed to resolve import "./master-flatten"`

- [ ] **Step 5: Implement `flattenMaster`**

Create `web/lib/master-flatten.ts`:

```ts
// Flatten a MASTER resume into labeled, comparable lines so `diffLines` can
// report what a save will change. The sibling `flattenResume` in resume-diff.ts
// does the same job for the TAILORED shape, which has different keys
// (`bullets` not `bullets_all`, one `summary` not `summary_options`) and is not
// reusable here.
//
// Section headings are the user-facing names, not the YAML keys, because these
// lines are shown to the person deciding whether to save.

type Master = Record<string, unknown>;

function asText(v: unknown): string {
  return (v ?? "").toString().trim();
}

function asList(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

function entryHeading(label: string, parts: string[]): string {
  const named = parts.filter(Boolean).join(" @ ");
  return named ? `§ ${label} — ${named}` : `§ ${label}`;
}

function bullets(entry: Record<string, unknown>, lines: string[]): void {
  for (const b of asList(entry.bullets_all)) {
    const text = asText(b);
    if (text) lines.push(`• ${text}`);
  }
}

export function flattenMaster(data: Master): string[] {
  const lines: string[] = [];

  const profile = (data.profile ?? {}) as Record<string, unknown>;
  const titles = asList(profile.identity_titles).map(asText).filter(Boolean);
  if (titles.length || profile.seniority) {
    lines.push("§ Who you are");
    if (titles.length) lines.push(`Titles: ${titles.join(", ")}`);
    if (profile.seniority) lines.push(`Level: ${asText(profile.seniority)}`);
  }

  const summaries = asList(data.summary_options).map(asText).filter(Boolean);
  if (summaries.length) {
    lines.push("§ How you describe yourself");
    for (const s of summaries) lines.push(`• ${s}`);
  }

  for (const [key, label] of [
    ["core_skills", "Skills you always list"],
    ["ats_adjacent_skills", "Skills to add when a job asks"],
  ] as const) {
    const items = asList(data[key]).map(asText).filter(Boolean);
    if (items.length) {
      lines.push(`§ ${label}`);
      for (const item of items) lines.push(`• ${item}`);
    }
  }

  // Canonical since PR #57: a mapping of group name to items.
  const skills = data.skills;
  if (skills && typeof skills === "object" && !Array.isArray(skills)) {
    const groups = Object.entries(skills as Record<string, unknown>);
    if (groups.length) {
      lines.push("§ Skill groups");
      for (const [group, items] of groups) {
        const listed = asList(items).map(asText).filter(Boolean).join(", ");
        lines.push(`• ${group}: ${listed}`);
      }
    }
  }

  for (const entry of asList(data.experience) as Record<string, unknown>[]) {
    lines.push(entryHeading("Jobs", [asText(entry.role), asText(entry.company)]));
    bullets(entry, lines);
  }

  for (const entry of asList(data.projects) as Record<string, unknown>[]) {
    lines.push(entryHeading("Projects", [asText(entry.name)]));
    bullets(entry, lines);
  }

  for (const entry of asList(data.education) as Record<string, unknown>[]) {
    lines.push(
      entryHeading("Education", [asText(entry.degree), asText(entry.school)]),
    );
  }

  return lines;
}
```

- [ ] **Step 6: Run to verify they pass**

Run: `cd web && npm run test`
Expected: PASS (9 tests)

- [ ] **Step 7: Confirm the build and lint are unaffected**

Run: `cd web && npm run lint && npm run build`
Expected: lint reports no *new* errors (the repo has 13 pre-existing, all in files this plan does not touch); build succeeds

- [ ] **Step 8: Commit**

```bash
git add web/package.json web/package-lock.json web/vitest.config.ts web/lib/master-flatten.ts web/lib/master-flatten.test.ts
git commit -m "feat: flatten the master resume into comparable lines"
```

---

## Task 6: The change-review panel

**Files:**
- Create: `web/components/change-review.tsx`
- Modify: `web/components/text-editor.tsx`

**Interfaces:**
- Consumes: `DiffLine` from `web/lib/resume-diff.ts`
- Produces: `<ChangeReview before={string[]} after={string[]} />`, and `TextEditor` rendering it

- [ ] **Step 1: Create the component**

Create `web/components/change-review.tsx`:

```tsx
"use client";

/**
 * What this save will actually do.
 *
 * The old signal was the words "unsaved changes", which asked the user to
 * approve something they could not see — worst of all right after an AI rewrite,
 * where the whole document may have moved. Both editors feed the same
 * `DiffLine[]`, so an AI rewrite and a hand edit are reported identically.
 */
import { useState } from "react";
import { ChevronDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import { diffLines, type DiffLine } from "@/lib/resume-diff";
import { cn } from "@/lib/utils";

export function ChangeReview({
  before,
  after,
  className,
}: {
  before: string[];
  after: string[];
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const diff = diffLines(before, after);
  const added = diff.filter((l) => l.type === "add").length;
  const removed = diff.filter((l) => l.type === "remove").length;

  if (!added && !removed) return null;

  const summary = [
    added ? `${added} added` : null,
    removed ? `${removed} removed` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className={cn("space-y-2", className)}>
      <Button
        size="sm"
        variant="ghost"
        className="h-7 gap-1.5 px-2 text-xs"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <ChevronDown
          className={cn("size-3.5 transition-transform", open && "rotate-180")}
        />
        {open ? "Hide changes" : "Review changes"}
        <span className="text-muted-foreground">· {summary}</span>
      </Button>

      {open ? (
        <div className="max-h-72 overflow-auto rounded-lg border border-border bg-muted/30 p-2 font-mono text-xs leading-relaxed">
          {diff.map((line, i) => (
            <DiffRow key={i} line={line} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function DiffRow({ line }: { line: DiffLine }) {
  if (line.type === "same") {
    return (
      <div className="text-muted-foreground/60">
        <span className="select-none pr-2"> </span>
        {line.text}
      </div>
    );
  }
  const add = line.type === "add";
  return (
    <div
      className={cn(
        "rounded-sm px-1",
        add
          ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
          : "bg-rose-500/10 text-rose-600 dark:text-rose-400",
      )}
    >
      <span className="select-none pr-2">{add ? "+" : "−"}</span>
      {line.text}
    </div>
  );
}
```

- [ ] **Step 2: Wire it into `TextEditor`**

In `web/components/text-editor.tsx`, add the import:

```tsx
import { ChangeReview } from "@/components/change-review";
```

Replace the dirty indicator span:

```tsx
          {dirty && (
            <span className="ml-2 text-amber-400">· unsaved changes</span>
          )}
```

with nothing (delete those three lines), and add the review panel directly above the `<Textarea>`:

```tsx
      {dirty ? (
        <ChangeReview before={base.split("\n")} after={val.split("\n")} />
      ) : null}
```

- [ ] **Step 3: Verify**

Run: `cd web && npm run lint && npm run build`
Expected: no new lint errors; build succeeds

- [ ] **Step 4: Commit**

```bash
git add web/components/change-review.tsx web/components/text-editor.tsx
git commit -m "feat: show what a save will change instead of that it will"
```

---

## Task 7: API client types and methods

**Files:**
- Modify: `web/lib/api.ts`

**Interfaces:**
- Produces: `MasterResume`, `ExperienceEntry`, `ProjectEntry`, `EducationEntry`, `MasterProfile` types; `api.getResumeStructured()`, `api.putResumeStructured(data)`

- [ ] **Step 1: Add the types**

In `web/lib/api.ts`, beside the other exported types (after `ProfileStrength`, around line 75):

```ts
/** One job. `bullets_all` is the full pool the tailor selects from per job. */
export type ExperienceEntry = {
  company: string;
  role: string;
  location?: string;
  start_date?: string;
  end_date?: string;
  bullets_all: string[];
};

export type ProjectEntry = {
  name: string;
  tech?: string;
  link?: string;
  bullets_all: string[];
};

export type EducationEntry = {
  school: string;
  degree: string;
  location?: string;
  start_date?: string;
  end_date?: string;
  gpa?: string;
  coursework?: string[];
};

export type MasterProfile = {
  identity_titles: string[];
  seniority: "student" | "new-grad" | "professional";
};

/**
 * The master resume as the structured editor sees it. Hand-written against
 * MASTER_RESUME_SCHEMA; the server validates, so drift shows up as a 400 with a
 * named field rather than a corrupt file. `skills` is a mapping — canonical
 * since PR #57, never the old {group, items} list.
 */
export type MasterResume = {
  profile?: MasterProfile;
  summary_options?: string[];
  core_skills?: string[];
  ats_adjacent_skills?: string[];
  skills?: Record<string, string[]>;
  experience?: ExperienceEntry[];
  projects?: ProjectEntry[];
  education?: EducationEntry[];
};
```

- [ ] **Step 2: Add the client methods**

In the `api` object, beside `getResume` / `putResume`:

```ts
  getResumeStructured: () =>
    http<{ data: MasterResume }>("/api/master-data/resume/structured"),
  putResumeStructured: (data: MasterResume) =>
    http<{ ok: boolean }>("/api/master-data/resume/structured", {
      method: "PUT",
      body: JSON.stringify({ data }),
    }),
```

- [ ] **Step 3: Verify**

Run: `cd web && npm run lint && npm run build`
Expected: no new lint errors; build succeeds

- [ ] **Step 4: Commit**

```bash
git add web/lib/api.ts
git commit -m "feat: api client for the structured master resume"
```

---

## Task 8: Section shell and the reorderable string list

The two primitives every section is built from. Nothing is wired into a page yet, so this task is reviewable on its own.

**Files:**
- Create: `web/components/master-data/section-card.tsx`
- Create: `web/components/master-data/string-list.tsx`

**Interfaces:**
- Produces:
  - `<SectionCard title={string} why={string} summary={string} defaultOpen?={boolean}>{children}</SectionCard>`
  - `<StringList value={string[]} onChange={(v: string[]) => void} itemLabel={string} multiline?={boolean} placeholder?={string} />`

- [ ] **Step 1: Create `SectionCard`**

Create `web/components/master-data/section-card.tsx`:

```tsx
"use client";

/**
 * One section of the resume, collapsed by default.
 *
 * The `why` line is where the template's YAML comments went. They existed to
 * explain the file to somebody reading raw YAML; the form is a better home for
 * the same information, and it reaches the people who need it most.
 */
import { useState, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";

export function SectionCard({
  title,
  why,
  summary,
  defaultOpen = false,
  children,
}: {
  title: string;
  why: string;
  summary: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="rounded-xl border border-border">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 rounded-xl px-4 py-3 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ChevronRight
          className={cn(
            "size-4 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-90",
          )}
        />
        <span className="flex-1">
          <span className="block font-medium">{title}</span>
          <span className="block text-xs text-muted-foreground">{why}</span>
        </span>
        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
          {summary}
        </span>
      </button>
      {open ? <div className="space-y-3 border-t border-border p-4">{children}</div> : null}
    </div>
  );
}
```

- [ ] **Step 2: Create `StringList`**

Create `web/components/master-data/string-list.tsx`:

```tsx
"use client";

/**
 * A list of short strings or bullets, with add, remove and reorder.
 *
 * Reordering is real work, not polish: the tailor selects the best bullets per
 * job, and a user who wants a bullet considered first has no other way to say
 * so. dnd-kit is already a dependency and already drives the applications
 * kanban.
 */
import {
  DndContext,
  closestCenter,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Plus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

export function StringList({
  value,
  onChange,
  itemLabel,
  multiline = false,
  placeholder,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  itemLabel: string;
  multiline?: boolean;
  placeholder?: string;
}) {
  // Index-based ids are stable for the lifetime of a drag, which is all
  // dnd-kit needs, and avoid inventing keys the server would have to carry.
  const ids = value.map((_, i) => `item-${i}`);

  const onDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    onChange(arrayMove(value, ids.indexOf(String(active.id)), ids.indexOf(String(over.id))));
  };

  const set = (index: number, next: string) =>
    onChange(value.map((v, i) => (i === index ? next : v)));

  return (
    <div className="space-y-2">
      <DndContext collisionDetection={closestCenter} onDragEnd={onDragEnd}>
        <SortableContext items={ids} strategy={verticalListSortingStrategy}>
          {value.map((item, index) => (
            <Row
              key={ids[index]}
              id={ids[index]}
              value={item}
              multiline={multiline}
              placeholder={placeholder}
              onChange={(next) => set(index, next)}
              onRemove={() => onChange(value.filter((_, i) => i !== index))}
            />
          ))}
        </SortableContext>
      </DndContext>

      <Button
        size="sm"
        variant="outline"
        className="gap-1.5"
        onClick={() => onChange([...value, ""])}
      >
        <Plus className="size-3.5" /> Add {itemLabel}
      </Button>
    </div>
  );
}

function Row({
  id,
  value,
  multiline,
  placeholder,
  onChange,
  onRemove,
}: {
  id: string;
  value: string;
  multiline: boolean;
  placeholder?: string;
  onChange: (v: string) => void;
  onRemove: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition } =
    useSortable({ id });

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className="flex items-start gap-2"
    >
      <button
        type="button"
        className="mt-2 cursor-grab text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label="Reorder"
        {...attributes}
        {...listeners}
      >
        <GripVertical className="size-4" />
      </button>
      {multiline ? (
        <Textarea
          value={value}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
          className="min-h-16 flex-1 text-sm"
        />
      ) : (
        <Input
          value={value}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
          className="flex-1"
        />
      )}
      <Button
        size="icon"
        variant="ghost"
        className="mt-0.5 shrink-0"
        onClick={onRemove}
        aria-label="Remove"
      >
        <X className="size-4" />
      </Button>
    </div>
  );
}
```

- [ ] **Step 3: Verify**

Run: `cd web && npm run lint && npm run build`
Expected: no new lint errors; build succeeds

- [ ] **Step 4: Commit**

```bash
git add web/components/master-data/section-card.tsx web/components/master-data/string-list.tsx
git commit -m "feat: section shell and reorderable list for the resume form"
```

---

## Task 9: The list-shaped sections

**Files:**
- Create: `web/components/master-data/section-identity.tsx`
- Create: `web/components/master-data/section-summaries.tsx`
- Create: `web/components/master-data/section-skills.tsx`

**Interfaces:**
- Consumes: `SectionCard`, `StringList` (Task 8); `MasterResume`, `MasterProfile` (Task 7)
- Produces: `<SectionIdentity value onChange />`, `<SectionSummaries value onChange />`, `<SectionSkills value onChange />` — each taking the whole `MasterResume` and an `onChange(patch: Partial<MasterResume>)`

- [ ] **Step 1: Create `SectionIdentity`**

Create `web/components/master-data/section-identity.tsx`:

```tsx
"use client";

import { SectionCard } from "./section-card";
import { StringList } from "./string-list";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import type { MasterProfile, MasterResume } from "@/lib/api";

const LEVELS: MasterProfile["seniority"][] = [
  "student",
  "new-grad",
  "professional",
];

export function SectionIdentity({
  value,
  onChange,
}: {
  value: MasterResume;
  onChange: (patch: Partial<MasterResume>) => void;
}) {
  const profile = value.profile ?? { identity_titles: [], seniority: "professional" };
  const titles = profile.identity_titles ?? [];

  const set = (patch: Partial<MasterProfile>) =>
    onChange({ profile: { ...profile, ...patch } });

  return (
    <SectionCard
      title="Who you are"
      why="Keeps tailored summaries truthful — they never claim a title you don't hold."
      summary={titles.length ? titles[0] : "not set"}
    >
      <div className="space-y-2">
        <Label>Your real job titles</Label>
        <StringList
          value={titles}
          onChange={(identity_titles) => set({ identity_titles })}
          itemLabel="title"
          placeholder="Software Engineer"
        />
      </div>

      <div className="space-y-2">
        <Label>Where you are in your career</Label>
        <Select
          value={profile.seniority}
          onValueChange={(v) => set({ seniority: v as MasterProfile["seniority"] })}
        >
          <SelectTrigger className="w-56">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {LEVELS.map((level) => (
              <SelectItem key={level} value={level}>
                {level}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </SectionCard>
  );
}
```

- [ ] **Step 2: Create `SectionSummaries`**

Create `web/components/master-data/section-summaries.tsx`:

```tsx
"use client";

import { SectionCard } from "./section-card";
import { StringList } from "./string-list";
import type { MasterResume } from "@/lib/api";

export function SectionSummaries({
  value,
  onChange,
}: {
  value: MasterResume;
  onChange: (patch: Partial<MasterResume>) => void;
}) {
  const summaries = value.summary_options ?? [];
  return (
    <SectionCard
      title="How you describe yourself"
      why="One of these is remixed for each job. More options means a closer fit."
      summary={summaries.length === 1 ? "1 version" : `${summaries.length} versions`}
    >
      <StringList
        value={summaries}
        onChange={(summary_options) => onChange({ summary_options })}
        itemLabel="version"
        multiline
        placeholder="Software Engineer with 3+ years building production web services…"
      />
    </SectionCard>
  );
}
```

- [ ] **Step 3: Create `SectionSkills`**

Create `web/components/master-data/section-skills.tsx`:

```tsx
"use client";

import { Plus, X } from "lucide-react";

import { SectionCard } from "./section-card";
import { StringList } from "./string-list";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { MasterResume } from "@/lib/api";

export function SectionSkills({
  value,
  onChange,
}: {
  value: MasterResume;
  onChange: (patch: Partial<MasterResume>) => void;
}) {
  const core = value.core_skills ?? [];
  const adjacent = value.ats_adjacent_skills ?? [];
  // Canonical mapping shape, per PR #57.
  const groups = Object.entries(value.skills ?? {});

  const setGroups = (next: [string, string[]][]) =>
    onChange({ skills: Object.fromEntries(next) });

  return (
    <>
      <SectionCard
        title="Skills you always list"
        why="These appear on every tailored resume, whatever the job asks for."
        summary={`${core.length}`}
      >
        <StringList
          value={core}
          onChange={(core_skills) => onChange({ core_skills })}
          itemLabel="skill"
          placeholder="Python"
        />
      </SectionCard>

      <SectionCard
        title="Skills to add when a job asks"
        why="Only credible neighbours of your real work — added when the posting calls for them."
        summary={`${adjacent.length}`}
      >
        <StringList
          value={adjacent}
          onChange={(ats_adjacent_skills) => onChange({ ats_adjacent_skills })}
          itemLabel="skill"
          placeholder="Docker"
        />
      </SectionCard>

      <SectionCard
        title="Skill groups"
        why="How skills are grouped under headings on the finished resume."
        summary={groups.length === 1 ? "1 group" : `${groups.length} groups`}
      >
        {groups.map(([name, items], index) => (
          <div key={index} className="space-y-2 rounded-lg border border-border p-3">
            <div className="flex items-center gap-2">
              <Label className="sr-only">Group name</Label>
              <Input
                value={name}
                placeholder="languages"
                onChange={(e) => {
                  const next: [string, string[]][] = [...groups];
                  next[index] = [e.target.value, items];
                  setGroups(next);
                }}
                className="max-w-56"
              />
              <div className="flex-1" />
              <Button
                size="icon"
                variant="ghost"
                aria-label="Remove group"
                onClick={() => setGroups(groups.filter((_, i) => i !== index))}
              >
                <X className="size-4" />
              </Button>
            </div>
            <StringList
              value={items}
              onChange={(nextItems) => {
                const next: [string, string[]][] = [...groups];
                next[index] = [name, nextItems];
                setGroups(next);
              }}
              itemLabel="skill"
              placeholder="Python"
            />
          </div>
        ))}
        <Button
          size="sm"
          variant="outline"
          className="gap-1.5"
          onClick={() => setGroups([...groups, ["", []]])}
        >
          <Plus className="size-3.5" /> Add group
        </Button>
      </SectionCard>
    </>
  );
}
```

- [ ] **Step 4: Verify**

Run: `cd web && npm run lint && npm run build`
Expected: no new lint errors; build succeeds

- [ ] **Step 5: Commit**

```bash
git add web/components/master-data/section-identity.tsx web/components/master-data/section-summaries.tsx web/components/master-data/section-skills.tsx
git commit -m "feat: identity, summary and skills sections for the resume form"
```

---

## Task 10: The entry-card sections

`experience`, `projects` and `education` share one shape — a list of records, each with fields and (for the first two) a bullet pool — so they share one component driven by a field descriptor.

**Files:**
- Create: `web/components/master-data/section-entries.tsx`

**Interfaces:**
- Consumes: `SectionCard`, `StringList` (Task 8); `MasterResume` (Task 7)
- Produces: `<SectionEntries kind={"experience" | "projects" | "education"} value onChange />`

- [ ] **Step 1: Create the component**

Create `web/components/master-data/section-entries.tsx`:

```tsx
"use client";

/**
 * Jobs, projects and education.
 *
 * One component for three sections because they are the same shape — a list of
 * records with a few fields, two of which also carry a bullet pool. Three
 * near-identical components would drift the moment one gained a field.
 */
import {
  DndContext,
  closestCenter,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Plus, X } from "lucide-react";

import { SectionCard } from "./section-card";
import { StringList } from "./string-list";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { MasterResume } from "@/lib/api";

type Kind = "experience" | "projects" | "education";
type Entry = Record<string, unknown>;

const FIELDS: Record<Kind, { key: string; label: string; placeholder?: string }[]> = {
  experience: [
    { key: "company", label: "Company", placeholder: "Example Corp" },
    { key: "role", label: "Job title", placeholder: "Software Engineer" },
    { key: "location", label: "Location", placeholder: "City, ST" },
    { key: "start_date", label: "Started", placeholder: "Jun 2022" },
    { key: "end_date", label: "Ended", placeholder: "Present" },
  ],
  projects: [
    { key: "name", label: "Project name", placeholder: "Applination" },
    { key: "tech", label: "Built with", placeholder: "Python, FastAPI" },
    { key: "link", label: "Link", placeholder: "https://…" },
  ],
  education: [
    { key: "school", label: "School", placeholder: "State University" },
    { key: "degree", label: "Degree", placeholder: "BS Computer Science" },
    { key: "location", label: "Location", placeholder: "City, ST" },
    { key: "start_date", label: "Started", placeholder: "Sep 2018" },
    { key: "end_date", label: "Ended", placeholder: "May 2022" },
    { key: "gpa", label: "GPA", placeholder: "3.8" },
  ],
};

const COPY: Record<Kind, { title: string; why: string; noun: string }> = {
  experience: {
    title: "Jobs you've had",
    why: "List every real bullet — the tailor picks the best ones for each job.",
    noun: "job",
  },
  projects: {
    title: "Projects",
    why: "Things you built that a posting might care about.",
    noun: "project",
  },
  education: {
    title: "Education",
    why: "Used to work out how your experience should be positioned.",
    noun: "school",
  },
};

const HAS_BULLETS: Record<Kind, boolean> = {
  experience: true,
  projects: true,
  education: false,
};

function label(kind: Kind, entry: Entry): string {
  if (kind === "projects") return String(entry.name || "Untitled project");
  if (kind === "education") return String(entry.school || "Untitled");
  return [entry.role, entry.company].filter(Boolean).join(" @ ") || "Untitled job";
}

export function SectionEntries({
  kind,
  value,
  onChange,
}: {
  kind: Kind;
  value: MasterResume;
  onChange: (patch: Partial<MasterResume>) => void;
}) {
  const entries = ((value[kind] ?? []) as unknown as Entry[]) ?? [];
  const ids = entries.map((_, i) => `${kind}-${i}`);
  const copy = COPY[kind];

  const commit = (next: Entry[]) =>
    onChange({ [kind]: next } as unknown as Partial<MasterResume>);

  const onDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    commit(arrayMove(entries, ids.indexOf(String(active.id)), ids.indexOf(String(over.id))));
  };

  const blank: Entry = HAS_BULLETS[kind] ? { bullets_all: [] } : {};

  return (
    <SectionCard
      title={copy.title}
      why={copy.why}
      summary={entries.length === 1 ? `1 ${copy.noun}` : `${entries.length} ${copy.noun}s`}
    >
      <DndContext collisionDetection={closestCenter} onDragEnd={onDragEnd}>
        <SortableContext items={ids} strategy={verticalListSortingStrategy}>
          {entries.map((entry, index) => (
            <EntryCard
              key={ids[index]}
              id={ids[index]}
              kind={kind}
              entry={entry}
              heading={label(kind, entry)}
              onChange={(next) =>
                commit(entries.map((e, i) => (i === index ? next : e)))
              }
              onRemove={() => commit(entries.filter((_, i) => i !== index))}
            />
          ))}
        </SortableContext>
      </DndContext>

      <Button
        size="sm"
        variant="outline"
        className="gap-1.5"
        onClick={() => commit([...entries, blank])}
      >
        <Plus className="size-3.5" /> Add {copy.noun}
      </Button>
    </SectionCard>
  );
}

function EntryCard({
  id,
  kind,
  entry,
  heading,
  onChange,
  onRemove,
}: {
  id: string;
  kind: Kind;
  entry: Entry;
  heading: string;
  onChange: (next: Entry) => void;
  onRemove: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition } =
    useSortable({ id });

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className="space-y-3 rounded-lg border border-border p-3"
    >
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="cursor-grab text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="Reorder"
          {...attributes}
          {...listeners}
        >
          <GripVertical className="size-4" />
        </button>
        <span className="flex-1 text-sm font-medium">{heading}</span>
        <Button size="icon" variant="ghost" aria-label="Remove" onClick={onRemove}>
          <X className="size-4" />
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {FIELDS[kind].map((field) => (
          <div key={field.key} className="grid gap-1.5">
            <Label htmlFor={`${id}-${field.key}`}>{field.label}</Label>
            <Input
              id={`${id}-${field.key}`}
              value={String(entry[field.key] ?? "")}
              placeholder={field.placeholder}
              onChange={(e) => onChange({ ...entry, [field.key]: e.target.value })}
            />
          </div>
        ))}
      </div>

      {HAS_BULLETS[kind] ? (
        <div className="space-y-2">
          <Label>What you did</Label>
          <StringList
            value={(entry.bullets_all as string[]) ?? []}
            onChange={(bullets_all) => onChange({ ...entry, bullets_all })}
            itemLabel="bullet"
            multiline
            placeholder="Built X using Y, cutting Z by N%."
          />
        </div>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 2: Verify**

Run: `cd web && npm run lint && npm run build`
Expected: no new lint errors; build succeeds

- [ ] **Step 3: Commit**

```bash
git add web/components/master-data/section-entries.tsx
git commit -m "feat: job, project and education entry cards"
```

---

## Task 11: Assemble the form and split the page

**Files:**
- Create: `web/components/master-data/resume-form.tsx`
- Modify: `web/app/master-data/page.tsx`

**Interfaces:**
- Consumes: every section from Tasks 9-10, `ChangeReview` (Task 6), `flattenMaster` (Task 5), `api.getResumeStructured` / `api.putResumeStructured` (Task 7)
- Produces: `<ResumeForm />`

- [ ] **Step 1: Create the form**

Create `web/components/master-data/resume-form.tsx`:

```tsx
"use client";

/**
 * The resume, as sections rather than a file.
 *
 * One Save for the whole document, matching the single structured PUT. Sections
 * collapse for navigation, not for saving — eight independent dirty states would
 * be harder to reason about than the file this replaces.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, RotateCcw, Save } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ChangeReview } from "@/components/change-review";
import { flattenMaster } from "@/lib/master-flatten";
import { api, type MasterResume } from "@/lib/api";

import { SectionIdentity } from "./section-identity";
import { SectionSummaries } from "./section-summaries";
import { SectionSkills } from "./section-skills";
import { SectionEntries } from "./section-entries";

export function ResumeForm() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["resume-structured"],
    queryFn: () => api.getResumeStructured().then((r) => r.data),
  });

  const [draft, setDraft] = useState<MasterResume | null>(null);
  const [baseline, setBaseline] = useState<MasterResume | null>(null);

  // Seed once the server answers, and re-seed if the file changed underneath —
  // the Advanced tab writes the same file, so trusting stale state here is how
  // one view silently saves over the other's work.
  const serverKey = JSON.stringify(data ?? null);
  const baselineKey = JSON.stringify(baseline ?? null);
  if (data && serverKey !== baselineKey && draft === null) {
    setBaseline(data);
    setDraft(data);
  }

  const save = useMutation({
    mutationFn: () => api.putResumeStructured(draft ?? {}),
    onSuccess: async () => {
      setBaseline(draft);
      toast.success("Saved");
      await qc.invalidateQueries({ queryKey: ["resume-structured"] });
      await qc.invalidateQueries({ queryKey: ["resume"] });
      await qc.invalidateQueries({ queryKey: ["profile-strength"] });
    },
    onError: (e) => toast.error(String(e)),
  });

  if (isLoading || !draft || !baseline) {
    return <Skeleton className="h-[60svh] w-full" />;
  }

  const patch = (p: Partial<MasterResume>) => setDraft({ ...draft, ...p });
  const dirty = JSON.stringify(draft) !== JSON.stringify(baseline);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <ChangeReview
          before={flattenMaster(baseline)}
          after={flattenMaster(draft)}
        />
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={!dirty || save.isPending}
            onClick={() => setDraft(baseline)}
          >
            <RotateCcw className="size-3" /> Reset
          </Button>
          <Button
            size="sm"
            disabled={!dirty || save.isPending}
            onClick={() => save.mutate()}
          >
            {save.isPending ? (
              <Loader2 className="size-3 animate-spin" />
            ) : (
              <Save className="size-3" />
            )}
            Save
          </Button>
        </div>
      </div>

      <div className="space-y-2">
        <SectionIdentity value={draft} onChange={patch} />
        <SectionSummaries value={draft} onChange={patch} />
        <SectionEntries kind="experience" value={draft} onChange={patch} />
        <SectionEntries kind="projects" value={draft} onChange={patch} />
        <SectionEntries kind="education" value={draft} onChange={patch} />
        <SectionSkills value={draft} onChange={patch} />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Give the resume tab Form and Advanced sub-tabs**

In `web/app/master-data/page.tsx`, add the import:

```tsx
import { ResumeForm } from "@/components/master-data/resume-form";
```

Replace the body of `ResumeEditor` so it wraps the existing raw editor in a nested `Tabs`, with the form first and default:

```tsx
function ResumeEditor() {
  return (
    <Tabs defaultValue="form">
      <TabsList>
        <TabsTrigger value="form">Form</TabsTrigger>
        <TabsTrigger value="raw">Advanced: YAML</TabsTrigger>
      </TabsList>
      <TabsContent value="form" className="mt-4">
        <ResumeForm />
      </TabsContent>
      <TabsContent value="raw" className="mt-4">
        <RawResumeEditor />
      </TabsContent>
    </Tabs>
  );
}
```

Rename the previous `ResumeEditor` body to `RawResumeEditor`, keeping its `EditableDoc` exactly as it is. In its `onSave`, add an invalidation of the structured query so switching back to the form re-reads the file:

```tsx
          await qc.invalidateQueries({ queryKey: ["resume-structured"] });
```

- [ ] **Step 3: Verify everything**

```bash
cd web && npm run test && npm run lint && npm run build
```
Expected: vitest passes; no new lint errors; build succeeds

```bash
cd D:/gitgit/internship_bot && .venv/Scripts/python.exe -m pytest -q
```
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add web/components/master-data/resume-form.tsx web/app/master-data/page.tsx
git commit -m "feat: edit the master resume as sections, not a YAML file"
```

---

## Task 12: Update CLAUDE.md and open the PR

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the architecture notes**

In `CLAUDE.md`, in the `server/` router list, add `master_data.py` and correct `config_api.py`'s description, which currently claims it owns the master-data text editors:

> `config_api.py` (per-user yaml editor; `GET /api/secrets` for stored-key status), `master_data.py` (resume/bio/story text editors plus `GET|PUT /api/master-data/resume/structured` — the structured editor behind the `/master-data` form; writes through `src/master_resume.render_master`, a ruamel round-trip that preserves comments and unmodelled keys),

In the `web/` section, update the `/master-data` description to mention the Form / Advanced split.

- [ ] **Step 2: Run everything one last time**

```bash
cd D:/gitgit/internship_bot && .venv/Scripts/python.exe -m pytest -q
cd web && npm run test && npm run lint && npm run build
```

- [ ] **Step 3: Commit and push**

```bash
git add CLAUDE.md
git commit -m "docs: record the master-data router and structured resume editor"
git push -u origin feat/master-data-form
```

- [ ] **Step 4: Open the PR**

Body must reference `Closes #56` only if specs 2 and 3 are also done; otherwise reference it as "Part 1 of #56" and leave the issue open. No Claude Code footer.

---

## Self-Review

**Spec coverage**

| spec requirement | task |
| --- | --- |
| `render_master` ruamel round-trip, comments and unmodelled keys survive | 1 |
| The eight form-owned keys named; absent key not deleted | 1 |
| `server/master_data.py`, endpoints moved at same URLs | 2 |
| `GET .../structured` via `load_master`, normalizes old `skills` | 3 |
| `PUT .../structured`, jsonschema, field-path errors | 4 |
| Tolerant on read, strict on write; text PUT stays permissive | 2, 3, 4 |
| vitest scoped to `web/lib`; the four named diff cases | 5 |
| `flattenMaster` mirroring `flattenResume` | 5 |
| One `DiffLine[]` renderer for text and structured | 5, 6 |
| Sections with plain-language labels and a "why" line | 8, 9, 10 |
| Entry cards, bullets as textareas, add/remove/reorder | 8, 10 |
| One Save for the document | 11 |
| Page split into `components/master-data/` | 9, 10, 11 |
| Raw editor kept as `Advanced` sub-tab | 11 |
| Tabs re-read from server rather than trusting stale state | 11 |
| `MASTER_RESUME_SCHEMA` unchanged; skills shape converted for validation only | Global Constraints; Task 4 Steps 3, 4b |

**Placeholder scan:** no TBD/TODO; every code step carries real code; no "similar to Task N".

**Type consistency:** `flattenMaster(data)` takes a `Record<string, unknown>`-compatible object and `MasterResume` satisfies it. `SectionCard` props (`title`, `why`, `summary`, `defaultOpen`) are used consistently in Tasks 9 and 10. `StringList` props (`value`, `onChange`, `itemLabel`, `multiline`, `placeholder`) match every call site. `onChange(patch: Partial<MasterResume>)` is the shared section contract and is what `resume-form.tsx` supplies via `patch`. `FORM_KEYS` is defined once in Task 1 and consumed in Task 4.
