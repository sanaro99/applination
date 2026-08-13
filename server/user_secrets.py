"""BYOK secret storage — the write and read halves of ``UserSecret``.

Every user brings their own API keys. Those keys must not sit in a YAML file:
``config.yaml`` is editable through the web UI, readable by anything with the
user's directory, and would end up in any backup or support bundle in plaintext.
So the secret-bearing fields are **diverted out of the config on write**, stored
Fernet-encrypted in ``UserSecret`` (``server/crypto.py``), and **merged back in
at read time** by ``deps.load_config``. The file on disk keeps the key present
but empty, which is what lets the editor still show the field's shape and
comments.

The round trip is:

    PUT /api/config  →  extract_secrets()  →  UserSecret (encrypted)
                        file written with the values blanked
    load_config(u)   →  merge_secrets()    →  in-memory config with keys present
    GET /api/config  →  reads the blanked file, so nothing leaks back out

``GET /api/secrets`` exists because a blanked file is indistinguishable from a
never-set key in the UI; it reports which names are set, masked, never the
plaintext.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlmodel import select

from .crypto import SecretKeyMissing, decrypt, encrypt, secret_key_configured
from .db import UserSecret, session

log = logging.getLogger("server.user_secrets")

# Dotted paths into the config tree whose values are secrets. Anything listed
# here is stripped from the file on write and re-merged on read.
#
# `llm.ollama.base_url` and `llm.nim.base_url` are deliberately absent — a
# hostname is not a credential, and blanking them would break local Ollama
# setups for no gain.
SECRET_PATHS: tuple[str, ...] = (
    "llm.claude.api_key",
    "llm.gemini.api_key",
    "llm.openrouter.api_key",
    "llm.deepseek.api_key",
    "llm.mistral.api_key",
    "llm.nim.api_key",
    "sources.adzuna.app_key",
    "sources.jsearch.rapidapi_key",
    "inbox.client_id",
    "inbox.client_secret",
)

# Secrets that are not config fields at all. The Gmail OAuth token used to live
# in the `Setting` table in plaintext; it is a refresh credential for the user's
# whole mailbox, so it belongs here with the API keys.
GMAIL_TOKEN = "inbox.gmail_token"


def _dig(cfg: dict, path: str) -> tuple[dict | None, str]:
    """Walk to the parent mapping of ``path``. Returns ``(None, leaf)`` if any
    intermediate key is missing or is not a mapping."""
    parts = path.split(".")
    node: object = cfg
    for part in parts[:-1]:
        if not isinstance(node, dict):
            return None, parts[-1]
        node = node.get(part)
    if not isinstance(node, dict):
        return None, parts[-1]
    return node, parts[-1]


# --------------------------------------------------------------------------
# storage
# --------------------------------------------------------------------------

def set_secret(user_id: int, name: str, value: str) -> None:
    """Store (or overwrite) one secret. An empty value deletes it, so clearing
    a field in the UI actually removes the credential rather than storing "" and
    leaving a stale key to be merged back in."""
    if not value:
        delete_secret(user_id, name)
        return
    ciphertext = encrypt(value)
    with session() as s:
        # noscope: UserSecret's primary key IS (user_id, name) — scoped by
        # construction, and it carries no `user_id`-nullable rows to filter.
        row = s.get(UserSecret, (user_id, name))
        if row:
            row.ciphertext = ciphertext
            row.updated_at = datetime.utcnow()
        else:
            row = UserSecret(user_id=user_id, name=name, ciphertext=ciphertext)
        s.add(row)
        s.commit()


def delete_secret(user_id: int, name: str) -> None:
    with session() as s:
        # noscope: composite primary key (user_id, name).
        row = s.get(UserSecret, (user_id, name))
        if row:
            s.delete(row)
            s.commit()


def get_secret(user_id: int, name: str) -> str | None:
    with session() as s:
        # noscope: composite primary key (user_id, name).
        row = s.get(UserSecret, (user_id, name))
    if row is None:
        return None
    try:
        return decrypt(row.ciphertext)
    except SecretKeyMissing:
        log.error(
            "secret %r for user %s could not be decrypted — APPLINATION_SECRET_KEY "
            "has changed or been lost; the user must re-enter it",
            name, user_id,
        )
        return None


def all_secrets(user_id: int) -> dict[str, str]:
    """Every decryptable secret for a user. Undecryptable rows are skipped with
    a log line rather than raising — one rotated key should not take down the
    whole config read path."""
    with session() as s:
        # noscope: UserSecret is keyed by (user_id, name) and this filters on
        # user_id explicitly; it is not in TENANT_MODELS because it has no
        # nullable-owner history to protect.
        rows = list(s.exec(select(UserSecret).where(UserSecret.user_id == user_id)))
    out: dict[str, str] = {}
    for row in rows:
        try:
            out[row.name] = decrypt(row.ciphertext)
        except SecretKeyMissing:
            log.error(
                "secret %r for user %s is undecryptable under the current key",
                row.name, user_id,
            )
    return out


def secret_names(user_id: int) -> list[str]:
    """Which secrets exist, without decrypting them. Safe when the Fernet key is
    missing entirely, which is what makes the UI able to say 'a key is stored
    but unreadable' instead of showing nothing."""
    with session() as s:
        # noscope: filtered on user_id; see all_secrets.
        rows = list(s.exec(select(UserSecret).where(UserSecret.user_id == user_id)))
    return sorted(r.name for r in rows)


# --------------------------------------------------------------------------
# config round trip
# --------------------------------------------------------------------------

def merge_secrets(cfg: dict, user_id: int) -> dict:
    """Merge this user's stored secrets into an in-memory config. Mutates and
    returns ``cfg``.

    Only fills fields that are empty on disk: a value the user typed straight
    into the YAML and has not yet round-tripped through a write should still
    work for the current request rather than being silently overridden by an
    older stored key.
    """
    stored = all_secrets(user_id)
    for path in SECRET_PATHS:
        value = stored.get(path)
        if not value:
            continue
        parent, leaf = _dig(cfg, path)
        if parent is None:
            # The user's config has no such section (an older or hand-trimmed
            # file). Build it, so a stored key is never dropped on the floor.
            parent = cfg
            parts = path.split(".")
            for part in parts[:-1]:
                nxt = parent.get(part)
                if not isinstance(nxt, dict):
                    nxt = {}
                    parent[part] = nxt
                parent = nxt
            leaf = parts[-1]
        if not str(parent.get(leaf) or "").strip():
            parent[leaf] = value
    return cfg


def extract_secrets(cfg: dict, user_id: int) -> list[str]:
    """Move every secret-bearing value in ``cfg`` into ``UserSecret`` and blank
    it in the mapping. Mutates ``cfg``; returns the paths that were stored.

    Works on a ruamel ``CommentedMap`` as happily as a plain dict, which is what
    lets the config editor preserve comments while still blanking the values.
    """
    stored: list[str] = []
    for path in SECRET_PATHS:
        parent, leaf = _dig(cfg, path)
        if parent is None:
            continue
        value = parent.get(leaf)
        if not isinstance(value, str) or not value.strip():
            continue
        set_secret(user_id, path, value.strip())
        parent[leaf] = ""
        stored.append(path)
    return stored


def masked(value: str) -> str:
    """A recognisable but useless rendering of a key: last four characters."""
    if len(value) <= 4:
        return "…"
    return f"…{value[-4:]}"


def secrets_status(user_id: int) -> dict:
    """What the Config page shows: which secrets are set, masked. Never returns
    a usable credential."""
    if not secret_key_configured():
        return {
            "key_configured": False,
            "secrets": [],
            "detail": (
                "APPLINATION_SECRET_KEY is not set, so API keys cannot be "
                "stored or read"
            ),
        }
    stored = all_secrets(user_id)
    names = secret_names(user_id)
    return {
        "key_configured": True,
        "secrets": [
            {
                "name": name,
                # A name present but absent from `stored` failed to decrypt.
                "readable": name in stored,
                "preview": masked(stored[name]) if name in stored else None,
            }
            for name in names
        ],
    }
