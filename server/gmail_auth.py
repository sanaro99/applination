"""Shared Gmail OAuth state — used by ``server/inbox.py`` and
``server/reminders.py``. Client id/secret live in ``config.yaml``; the token
(with refresh token + account email) lives in the ``Setting`` table so it
never ends up in a config.yaml diff.
"""
from __future__ import annotations

import json
import logging

from google.oauth2.credentials import Credentials

from .db import Setting, session
from .deps import load_config

log = logging.getLogger("server.gmail_auth")

_TOKEN_KEY = "inbox_oauth_token"


def inbox_cfg() -> dict:
    return load_config().get("inbox") or {}


def _get_setting(key: str) -> str:
    with session() as s:
        row = s.get(Setting, key)
        return row.value if row else ""


def _set_setting(key: str, value: str) -> None:
    with session() as s:
        row = s.get(Setting, key)
        if row is None:
            row = Setting(key=key, value="")
        row.value = value
        s.add(row)
        s.commit()


def _load_token_blob() -> dict | None:
    raw = _get_setting(_TOKEN_KEY)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def save_token(token_json: dict, account_email: str) -> None:
    _set_setting(_TOKEN_KEY, json.dumps({"token": token_json, "account_email": account_email}))


def clear_token() -> None:
    _set_setting(_TOKEN_KEY, "")


def account_email() -> str | None:
    blob = _load_token_blob()
    return blob.get("account_email") if blob else None


def is_connected() -> bool:
    cfg = inbox_cfg()
    return bool(cfg.get("client_id")) and bool(cfg.get("client_secret")) and _load_token_blob() is not None


def get_credentials() -> Credentials | None:
    """Return live, refreshed credentials, or None if not connected."""
    from src.gmail_oauth import credentials_from_token_json, credentials_to_token_json

    cfg = inbox_cfg()
    client_id = str(cfg.get("client_id") or "")
    client_secret = str(cfg.get("client_secret") or "")
    blob = _load_token_blob()
    if not client_id or not client_secret or not blob:
        return None

    creds = credentials_from_token_json(blob["token"], client_id, client_secret)
    # credentials_from_token_json() refreshes in place; persist the new access token.
    refreshed = credentials_to_token_json(creds)
    if refreshed.get("token") != blob["token"].get("token"):
        save_token(refreshed, blob.get("account_email", ""))
    return creds
