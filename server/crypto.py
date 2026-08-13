"""Symmetric encryption for user-held secrets (LLM API keys, Gmail tokens).

Everything here is keyed by ``APPLINATION_SECRET_KEY``, a Fernet key the server
holds and the database never sees. Losing it makes every stored secret
undecryptable and forces every user to re-enter their keys, so it belongs in
``applination.env`` *and* in a backup outside the ZFS snapshot — a snapshot that
dies with the pool takes the key with it.

Generate one with::

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

PR 2 ships the table and these helpers. The readers that merge decrypted secrets
into a per-user config live in PR 3.
"""
from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken

ENV_VAR = "APPLINATION_SECRET_KEY"


class SecretKeyMissing(RuntimeError):
    """Raised when a secret operation is attempted with no key configured."""


def _fernet() -> Fernet:
    raw = (os.environ.get(ENV_VAR) or "").strip()
    if not raw:
        raise SecretKeyMissing(
            f"{ENV_VAR} is not set — cannot read or write encrypted user "
            "secrets. Generate one with: python -c \"from cryptography.fernet "
            'import Fernet; print(Fernet.generate_key().decode())"'
        )
    try:
        return Fernet(raw.encode())
    except (ValueError, TypeError) as e:
        raise SecretKeyMissing(
            f"{ENV_VAR} is not a valid Fernet key (expect 32 url-safe "
            f"base64-encoded bytes): {e}"
        ) from e


def secret_key_configured() -> bool:
    """True if a usable key is present. Lets callers degrade with a clear
    message instead of raising from deep inside a request."""
    try:
        _fernet()
    except SecretKeyMissing:
        return False
    return True


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a stored secret.

    Raises ``SecretKeyMissing`` if the key was rotated or lost — deliberately
    not returning "" or None, because a silently-empty API key would surface far
    downstream as a confusing provider auth error.
    """
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as e:
        raise SecretKeyMissing(
            f"stored secret could not be decrypted with the current {ENV_VAR} "
            "— the key was probably rotated or replaced"
        ) from e
