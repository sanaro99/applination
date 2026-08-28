"""Config + master-data editor endpoints — per-user.

Before PR 3 this router was owner-only, because every path it touched was the
one global ``config.yaml`` / ``master_data/``. Both are now per-account, so
every endpoint here is plain ``require_user`` again and resolves through
``UserPaths``. There is no global file left for one account to reach.

Secrets never make the round trip: ``PUT /api/config`` diverts API keys into
encrypted storage and blanks them in the file, so the ``GET`` that follows
returns a document with the fields present but empty. ``GET /api/secrets``
reports which ones are actually set.
"""
from __future__ import annotations
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import require_user
from .db import User
from .deps import load_config, load_config_redacted, paths_for, update_config
from .user_secrets import extract_secrets, secrets_status

router = APIRouter(prefix="/api", tags=["config"])


class TextBody(BaseModel):
    text: str


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@router.get("/config")
def get_config(user: User = Depends(require_user)) -> dict:
    return {"text": _read(paths_for(user).config_path)}


@router.put("/config")
def put_config(body: TextBody, user: User = Depends(require_user)) -> dict:
    """Save the raw YAML, diverting any secrets it contains.

    The saved text is not byte-identical to what was submitted when it carried a
    key: the value is stored encrypted and written back as ``""``. That is
    visible to the user on the next load, which is the intended behaviour —
    silently keeping the key in the file would be the surprise.
    """
    try:
        parsed = yaml.safe_load(body.text)
    except yaml.YAMLError as e:
        raise HTTPException(400, f"invalid YAML: {e}") from e
    if parsed is not None and not isinstance(parsed, dict):
        raise HTTPException(400, "config must be a YAML mapping")

    paths = paths_for(user)
    text = body.text
    # Only pay the ruamel round trip when there is actually a secret to divert,
    # so an ordinary edit is saved exactly as typed.
    if parsed:
        from ruamel.yaml import YAML

        yamlrt = YAML()
        yamlrt.preserve_quotes = True
        doc = yamlrt.load(body.text)
        if doc is not None and extract_secrets(doc, paths.user_id):
            import io

            buf = io.StringIO()
            yamlrt.dump(doc, buf)
            text = buf.getvalue()

    _write(paths.config_path, text)
    return {"ok": True}


class KeywordsBody(BaseModel):
    keywords: list[str]


@router.get("/search/keywords")
def get_search_keywords(user: User = Depends(require_user)) -> dict:
    """The target-roles list only (`search.keywords`), for the Master Data
    'Target roles' tab. Kept separate from /api/onboarding/search, which also
    writes remote_ok/onsite_cities/countries — this endpoint must not touch
    those when a user only edits their roles after onboarding."""
    cfg = load_config(user) or {}
    keywords = (cfg.get("search") or {}).get("keywords") or []
    return {"keywords": [str(k) for k in keywords]}


@router.put("/search/keywords")
def put_search_keywords(body: KeywordsBody, user: User = Depends(require_user)) -> dict:
    def mut(data: dict) -> None:
        search = data.get("search")
        if search is None:
            search = {}
            data["search"] = search
        search["keywords"] = [k.strip() for k in body.keywords if k.strip()]
    update_config(user, mut)
    return {"ok": True}


@router.get("/secrets")
def get_secrets(user: User = Depends(require_user)) -> dict:
    """Which API keys are stored, masked. Never returns a usable credential."""
    return secrets_status(user.id)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Structured config — the four sections the /config forms own
#
# `llm` is left out because /workflows already edits it visually, `inbox`
# because the Gmail connect card owns it, `user` because onboarding sets it,
# and `pricing` because it is a developer knob. The raw editor still reaches
# all four.
# --------------------------------------------------------------------------

class StructuredBody(BaseModel):
    data: dict


# Defaults mirror config.example.yaml, for a file written before a key existed.
_SEARCH_DEFAULTS: dict = {
    "keywords": [],
    "min_match_score": 55,
    "max_jobs_per_day": 20,
    "remote_ok": True,
    "onsite_cities": [],
    "countries": ["us"],
}
_OUTPUT_DEFAULTS: dict = {
    "produce_pdf": True,
    "font_name": "Times New Roman",
    "base_font_size": 10.0,
    "margins_inches": 0.25,
}
_REMINDER_DEFAULTS: dict = {
    "digest_enabled": False,
    "digest_to": "",
    "deadline_window_days": 7,
    "follow_up_days": 10,
}


def _pick(section: object, defaults: dict) -> dict:
    src = section if isinstance(section, dict) else {}
    return {k: src.get(k, default) for k, default in defaults.items()}


@router.get("/config/structured")
def get_config_structured(user: User = Depends(require_user)) -> dict:
    """The form's four sections, read from the redacted config.

    Two of the leaves under ``sources`` are API keys. What actually keeps them
    out of the response is that only named fields are picked — but this reads
    the redacted document anyway, so a later field added here cannot quietly
    become a way to read a credential back out.
    """
    cfg = load_config_redacted(user) or {}
    sources = cfg.get("sources") if isinstance(cfg.get("sources"), dict) else {}
    greenhouse = sources.get("greenhouse")
    extra = (
        greenhouse.get("extra_companies")
        if isinstance(greenhouse, dict)
        else None
    )
    return {
        "data": {
            "search": _pick(cfg.get("search"), _SEARCH_DEFAULTS),
            "sources": {
                # File order, and only blocks that actually have a switch — the
                # form offers what this config has, not what some list in the
                # browser says it should have.
                "toggles": [
                    {"key": key, "enabled": bool(block.get("enabled"))}
                    for key, block in sources.items()
                    if isinstance(block, dict) and "enabled" in block
                ],
                "greenhouse_extra_companies": [str(c) for c in (extra or [])],
            },
            "output": _pick(cfg.get("output"), _OUTPUT_DEFAULTS),
            "reminders": _pick(cfg.get("reminders"), _REMINDER_DEFAULTS),
        }
    }


def _is_int(value: object) -> bool:
    # bool is a subclass of int, and `produce_pdf: true` arriving where a count
    # belongs should read as the mistake it is.
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_str_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _config_errors(data: dict) -> list[str]:
    """Every problem with the payload, named by the field the form shows.

    Bounds are what a person could plausibly mean: a match score outside 0-100
    silently keeps every job or none, and a 400pt font is not something anyone
    recovers from by reading a stack trace.
    """
    errors: list[str] = []
    search = data.get("search") or {}
    output = data.get("output") or {}
    reminders = data.get("reminders") or {}
    sources = data.get("sources") or {}

    for key in ("keywords", "onsite_cities", "countries"):
        if key in search and not _is_str_list(search[key]):
            errors.append(f"{key} must be a list of text values")
    if "remote_ok" in search and not isinstance(search["remote_ok"], bool):
        errors.append("remote_ok must be true or false")
    if "min_match_score" in search and not (
        _is_int(search["min_match_score"]) and 0 <= search["min_match_score"] <= 100
    ):
        errors.append("min_match_score must be a whole number between 0 and 100")
    if "max_jobs_per_day" in search and not (
        _is_int(search["max_jobs_per_day"]) and 1 <= search["max_jobs_per_day"] <= 500
    ):
        errors.append("max_jobs_per_day must be a whole number between 1 and 500")

    if "produce_pdf" in output and not isinstance(output["produce_pdf"], bool):
        errors.append("produce_pdf must be true or false")
    if "font_name" in output and not str(output["font_name"] or "").strip():
        errors.append("font_name cannot be empty")
    if "base_font_size" in output and not (
        _is_number(output["base_font_size"]) and 6 <= output["base_font_size"] <= 24
    ):
        errors.append("base_font_size must be between 6 and 24")
    if "margins_inches" in output and not (
        _is_number(output["margins_inches"]) and 0 <= output["margins_inches"] <= 2
    ):
        errors.append("margins_inches must be between 0 and 2")

    if "digest_enabled" in reminders and not isinstance(
        reminders["digest_enabled"], bool
    ):
        errors.append("digest_enabled must be true or false")
    if "digest_to" in reminders and not isinstance(reminders["digest_to"], str):
        errors.append("digest_to must be an email address or empty")
    for key in ("deadline_window_days", "follow_up_days"):
        if key in reminders and not (
            _is_int(reminders[key]) and 0 <= reminders[key] <= 365
        ):
            errors.append(f"{key} must be a whole number of days between 0 and 365")

    toggles = sources.get("toggles")
    if toggles is not None and (
        not isinstance(toggles, list)
        or any(
            not isinstance(t, dict)
            or not isinstance(t.get("key"), str)
            or not isinstance(t.get("enabled"), bool)
            for t in toggles
        )
    ):
        errors.append("sources must be a list of {key, enabled} switches")
    if "greenhouse_extra_companies" in sources and not _is_str_list(
        sources["greenhouse_extra_companies"]
    ):
        errors.append("greenhouse_extra_companies must be a list of company slugs")

    return errors


def _set_changed(node: dict, key: str, value: object) -> None:
    """Assign only when the value actually differs.

    Reassigning an equal value replaces the ruamel node and drops the
    template's quoting with it, so a user who edited one field would find the
    other twenty rewritten. ``!=`` works across ruamel scalar types, which
    compare equal to the plain values they wrap.
    """
    if key not in node or node[key] != value:
        node[key] = value


def _section(doc: dict, name: str) -> dict:
    node = doc.get(name)
    if not isinstance(node, dict):
        node = {}
        doc[name] = node
    return node


def _clean(values: list) -> list[str]:
    return [v.strip() for v in values if v.strip()]


@router.put("/config/structured")
def put_config_structured(
    body: StructuredBody, user: User = Depends(require_user)
) -> dict:
    """Validate, then merge into the config the user already has.

    Writes through ``update_config``, which round-trips via ruamel so the
    template's comments survive — they are most of what config.yaml is — and
    which runs ``extract_secrets`` afterwards, so API keys stay diverted into
    encrypted storage. Only the fields the form renders are touched, so
    ``sources.adzuna.app_key`` and its neighbour are never reached by name.
    """
    errors = _config_errors(body.data)
    if errors:
        raise HTTPException(400, "; ".join(errors[:3]))

    search = body.data.get("search") or {}
    sources = body.data.get("sources") or {}
    output = body.data.get("output") or {}
    reminders = body.data.get("reminders") or {}

    def mut(doc: dict) -> None:
        if search:
            node = _section(doc, "search")
            if "keywords" in search:
                _set_changed(node, "keywords", _clean(search["keywords"]))
            for key in ("min_match_score", "max_jobs_per_day", "remote_ok"):
                if key in search:
                    _set_changed(node, key, search[key])
            for key in ("onsite_cities", "countries"):
                if key in search:
                    _set_changed(node, key, _clean(search[key]))

        block_root = doc.get("sources")
        if isinstance(block_root, dict):
            for toggle in sources.get("toggles") or []:
                block = block_root.get(toggle["key"])
                # A switch for a scraper this config has no block for would be
                # a key `main.fetch_all` never reads. Ignore rather than invent.
                if isinstance(block, dict):
                    _set_changed(block, "enabled", toggle["enabled"])
            greenhouse = block_root.get("greenhouse")
            if isinstance(greenhouse, dict) and "greenhouse_extra_companies" in sources:
                _set_changed(
                    greenhouse,
                    "extra_companies",
                    _clean(sources["greenhouse_extra_companies"]),
                )

        for name, values, fields in (
            ("output", output, _OUTPUT_DEFAULTS),
            ("reminders", reminders, _REMINDER_DEFAULTS),
        ):
            if not values:
                continue
            node = _section(doc, name)
            for key in fields:
                if key in values:
                    _set_changed(node, key, values[key])

    update_config(user, mut)
    return {"ok": True}
