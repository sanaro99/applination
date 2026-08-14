"""Shared Gmail OAuth state — used by ``server/inbox.py`` and
``server/reminders.py``.

Client id/secret come from the user's own ``config.yaml`` (themselves diverted
into encrypted storage — see ``user_secrets.SECRET_PATHS``). The token blob,
which carries a **refresh token for the user's entire mailbox**, lives in
``UserSecret`` and is Fernet-encrypted at rest.

PR 2 kept this blob in the ``Setting`` table. That was already tenant-scoped —
``Setting``'s primary key is ``(user_id, key)`` — but it sat in the database in
plaintext, which for a long-lived mailbox credential is the wrong default: a
database dump, a backup, or a `SELECT * FROM setting` while debugging would
hand it over. PR 3 moves it beside the API keys. ``server/migrations`` carries
the data migration for anyone who connected Gmail under PR 2.
"""
from __future__ import annotations

import json
import logging

from google.oauth2.credentials import Credentials

from .crypto import SecretKeyMissing
from .deps import load_config
from .user_secrets import GMAIL_TOKEN, delete_secret, get_secret, set_secret

log = logging.getLogger("server.gmail_auth")


def inbox_cfg(user: object) -> dict:
    return load_config(user).get("inbox") or {}


def _load_token_blob(user_id: int) -> dict | None:
    try:
        raw = get_secret(user_id, GMAIL_TOKEN)
    except SecretKeyMissing:
        log.error("cannot read the Gmail token: no usable APPLINATION_SECRET_KEY")
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log.error("stored Gmail token for user %s is not valid JSON", user_id)
        return None


def save_token(user_id: int, token_json: dict, account_email: str) -> None:
    set_secret(
        user_id,
        GMAIL_TOKEN,
        json.dumps({"token": token_json, "account_email": account_email}),
    )


def clear_token(user_id: int) -> None:
    """Disconnect. Deletes the row rather than blanking it, so a disconnected
    account leaves no ciphertext behind."""
    delete_secret(user_id, GMAIL_TOKEN)


def account_email(user_id: int) -> str | None:
    blob = _load_token_blob(user_id)
    return blob.get("account_email") if blob else None


def is_connected(user: object) -> bool:
    cfg = inbox_cfg(user)
    user_id = getattr(user, "id", user)
    return (
        bool(cfg.get("client_id"))
        and bool(cfg.get("client_secret"))
        and _load_token_blob(user_id) is not None
    )


def get_credentials(user: object) -> Credentials | None:
    """Return live, refreshed credentials, or None if not connected."""
    from src.gmail_oauth import credentials_from_token_json, credentials_to_token_json

    cfg = inbox_cfg(user)
    user_id = getattr(user, "id", user)
    client_id = str(cfg.get("client_id") or "")
    client_secret = str(cfg.get("client_secret") or "")
    blob = _load_token_blob(user_id)
    if not client_id or not client_secret or not blob:
        return None

    creds = credentials_from_token_json(blob["token"], client_id, client_secret)
    # credentials_from_token_json() refreshes in place; persist the new access token.
    refreshed = credentials_to_token_json(creds)
    if refreshed.get("token") != blob["token"].get("token"):
        save_token(user_id, refreshed, blob.get("account_email", ""))
    return creds
