"""move the Gmail OAuth token from `setting` into encrypted `usersecret`

Revision ID: a4e1f27c9b03
Revises: 7f3c1a9d2b84
Create Date: 2026-08-13 18:30:00.000000

PR 2 stored the Gmail token as a plaintext ``setting`` row. That was already
tenant-scoped — ``setting``'s primary key is ``(user_id, key)`` — but the value
is a refresh credential for the user's entire mailbox sitting unencrypted in the
database, where a dump, a backup, or a stray ``SELECT *`` while debugging hands
it over. PR 3 moves it beside the API keys in ``usersecret``, Fernet-encrypted
under APPLINATION_SECRET_KEY.

The move is conditional on that key being available. Without it the token cannot
be encrypted, and the migration deliberately **leaves the plaintext row alone
and continues** rather than failing or deleting it: an operator who upgrades
before setting the key should end up with a working install and a disconnected
Gmail (re-connectable in two clicks), not a failed deploy or a destroyed
credential. The warning says exactly that.

``downgrade`` reverses it only when the key is present, for the same reason.
"""
from __future__ import annotations

import logging

import sqlalchemy as sa
from alembic import op

revision: str = "a4e1f27c9b03"
down_revision: str | None = "7f3c1a9d2b84"
branch_labels: str | None = None
depends_on: str | None = None

log = logging.getLogger("alembic.runtime.migration")

_OLD_SETTING_KEY = "inbox_oauth_token"
_SECRET_NAME = "inbox.gmail_token"


def _crypto():
    """The crypto helpers, or None if no usable key is configured."""
    try:
        from server.crypto import decrypt, encrypt, secret_key_configured
    except Exception:  # noqa: BLE001 — never let an import break a migration
        return None
    if not secret_key_configured():
        return None
    return encrypt, decrypt


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT user_id, value FROM setting "
            "WHERE key = :k AND value IS NOT NULL AND value <> ''"
        ),
        {"k": _OLD_SETTING_KEY},
    ).fetchall()
    if not rows:
        return

    crypto = _crypto()
    if crypto is None:
        log.warning(
            "%d Gmail OAuth token(s) left in the `setting` table: "
            "APPLINATION_SECRET_KEY is not set, so they cannot be encrypted. "
            "The affected users will show as disconnected and can reconnect "
            "Gmail from the Config page. Nothing was deleted.",
            len(rows),
        )
        return
    encrypt, _decrypt = crypto

    from datetime import datetime

    for user_id, value in rows:
        # INSERT-then-DELETE, both inside the migration's transaction, so a
        # failure between them cannot lose the token.
        existing = conn.execute(
            sa.text(
                "SELECT 1 FROM usersecret WHERE user_id = :u AND name = :n"
            ),
            {"u": user_id, "n": _SECRET_NAME},
        ).first()
        if existing:
            # Already moved (a re-run, or the user reconnected). The newer
            # encrypted value wins; drop the stale plaintext.
            pass
        else:
            conn.execute(
                sa.text(
                    "INSERT INTO usersecret (user_id, name, ciphertext, updated_at) "
                    "VALUES (:u, :n, :c, :t)"
                ),
                {
                    "u": user_id,
                    "n": _SECRET_NAME,
                    "c": encrypt(value),
                    "t": datetime.utcnow(),
                },
            )
        conn.execute(
            sa.text("DELETE FROM setting WHERE user_id = :u AND key = :k"),
            {"u": user_id, "k": _OLD_SETTING_KEY},
        )
    log.info("moved %d Gmail token(s) into encrypted storage", len(rows))


def downgrade() -> None:
    conn = op.get_bind()
    crypto = _crypto()
    if crypto is None:
        log.warning(
            "cannot move Gmail tokens back to `setting`: no usable "
            "APPLINATION_SECRET_KEY. Leaving them encrypted; users can "
            "reconnect Gmail if needed."
        )
        return
    _encrypt, decrypt = crypto

    rows = conn.execute(
        sa.text("SELECT user_id, ciphertext FROM usersecret WHERE name = :n"),
        {"n": _SECRET_NAME},
    ).fetchall()
    for user_id, ciphertext in rows:
        try:
            plaintext = decrypt(ciphertext)
        except Exception:  # noqa: BLE001 — a rotated key; skip, do not crash
            log.warning(
                "Gmail token for user %s could not be decrypted; leaving it",
                user_id,
            )
            continue
        conn.execute(
            sa.text("DELETE FROM setting WHERE user_id = :u AND key = :k"),
            {"u": user_id, "k": _OLD_SETTING_KEY},
        )
        conn.execute(
            sa.text(
                "INSERT INTO setting (user_id, key, value) "
                "VALUES (:u, :k, :v)"
            ),
            {"u": user_id, "k": _OLD_SETTING_KEY, "v": plaintext},
        )
        conn.execute(
            sa.text("DELETE FROM usersecret WHERE user_id = :u AND name = :n"),
            {"u": user_id, "n": _SECRET_NAME},
        )
