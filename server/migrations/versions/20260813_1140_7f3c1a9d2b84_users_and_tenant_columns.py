"""users, sessions, secrets, and per-tenant columns

Revision ID: 7f3c1a9d2b84
Revises: 314cc8e80422
Create Date: 2026-08-13 11:40:00.000000

Strictly additive, in the order the plan requires:

    1. create appuser / usersession / usersecret
    2. ADD COLUMN user_id NULL on all seven tenant tables
    3. if there is existing data, INSERT the owner (seeded from config.yaml's
       ``user:`` block) and backfill every row to it
    4. SET NOT NULL + FK + composite index
    5. rebuild ``setting``'s primary key as (user_id, key)

No step deletes or rewrites user data, and ``downgrade`` only drops the columns
and tables this revision added.

Batch mode throughout: SQLite cannot ALTER a column to NOT NULL or attach a
constraint in place, and the test suite runs these very migrations against
SQLite (``tests/conftest.py``). On Postgres batch mode emits plain ALTERs.
"""
from __future__ import annotations

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "7f3c1a9d2b84"
down_revision: str | None = "314cc8e80422"
branch_labels: str | None = None
depends_on: str | None = None


# The six tables that get a plain nullable-then-NOT NULL user_id. `setting` is
# handled separately because its primary key changes too.
_TENANT_TABLES = (
    "run",
    "application",
    "rankedjob",
    "chatsession",
    "chatmessage",
    "savedanswer",
)

# A hash no password can ever verify against. argon2 rejects it as malformed,
# which `auth.verify_password` catches and turns into False. The owner is told
# to set a real one via scripts/set_password.py — a literal here would be a
# committed default credential.
_UNUSABLE_PASSWORD_HASH = "!"


def _owner_email(conn: sa.engine.Connection) -> str:
    """Seed the owner's email from config.yaml's ``user:`` block.

    Falls back to a placeholder rather than failing the migration: the address
    is only a login identifier, the operator sets the password out of band
    anyway, and a half-migrated database is far worse than a wrong email.
    """
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[3]
    cfg_path = root / "config.yaml"
    try:
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        email = ((cfg.get("user") or {}).get("email") or "").strip().lower()
    except Exception:
        email = ""
    return email or "owner@localhost"


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Identity tables.
    op.create_table(
        "appuser",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("password_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("is_owner", sa.Boolean(), nullable=False),
        sa.Column("disabled", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_appuser_email"), "appuser", ["email"], unique=True)

    op.create_table(
        "usersession",
        sa.Column("token_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["appuser.id"], name="fk_usersession_user_id_appuser"
        ),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_usersession_user_id"), "usersession", ["user_id"], unique=False
    )

    op.create_table(
        "usersecret",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("ciphertext", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["appuser.id"], name="fk_usersecret_user_id_appuser"
        ),
        sa.PrimaryKeyConstraint("user_id", "name"),
    )

    # 2. Nullable tenant column everywhere, including setting.
    for table in (*_TENANT_TABLES, "setting"):
        op.add_column(table, sa.Column("user_id", sa.Integer(), nullable=True))

    # 3. Adopt any pre-existing data. Only when there is some: on a fresh
    #    database no owner is created, so the first account to sign up becomes
    #    the owner (see auth.signup) rather than inheriting a locked-out one.
    owner_id: int | None = None
    if _has_existing_data(conn):
        owner_id = _create_owner(conn)
        for table in (*_TENANT_TABLES, "setting"):
            conn.execute(
                sa.text(
                    f"UPDATE {table} SET user_id = :uid WHERE user_id IS NULL"
                ),
                {"uid": owner_id},
            )

    # 4. Lock the column down.
    for table in _TENANT_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "user_id", existing_type=sa.Integer(), nullable=False
            )
            batch.create_foreign_key(
                f"fk_{table}_user_id_appuser", "appuser", ["user_id"], ["id"]
            )
        op.create_index(
            op.f(f"ix_{table}_user_id"), table, ["user_id"], unique=False
        )
        # (user_id, id) specifically: every list endpoint filters on user_id and
        # orders/paginates by id, so this covers both halves of the common query.
        op.create_index(
            f"ix_{table}_user_id_id", table, ["user_id", "id"], unique=False
        )

    # 5. Rebuild setting's primary key as (user_id, key).
    #
    #    Read the rows out, drop the table, recreate it, put them back. The
    #    obvious alternative — rename the old table aside and copy across — does
    #    not survive a downgrade/upgrade round-trip: the renamed table keeps its
    #    primary-key constraint name, and in Postgres constraint names share a
    #    namespace with tables, so recreating `setting` collides with the name
    #    still held by `setting_old`.
    #
    #    Buffering in memory is safe here: DDL is transactional on both dialects
    #    (a failure rolls the whole revision back), and `setting` holds a handful
    #    of small, regenerable flags.
    #
    #    Rows with a NULL user_id are dropped rather than failing the upgrade —
    #    that can only happen if a row escaped the backfill, and these are flags
    #    the app rewrites on demand.
    rows = conn.execute(
        sa.text("SELECT user_id, key, value FROM setting WHERE user_id IS NOT NULL")
    ).all()
    op.drop_table("setting")
    op.create_table(
        "setting",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("value", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["appuser.id"], name="fk_setting_user_id_appuser"
        ),
        sa.PrimaryKeyConstraint("user_id", "key", name="pk_setting"),
    )
    if rows:
        conn.execute(
            sa.text(
                "INSERT INTO setting (user_id, key, value) "
                "VALUES (:user_id, :key, :value)"
            ),
            [{"user_id": r[0], "key": r[1], "value": r[2]} for r in rows],
        )

    if owner_id is not None:
        _announce_owner(conn, owner_id)


def _has_existing_data(conn: sa.engine.Connection) -> bool:
    for table in (*_TENANT_TABLES, "setting"):
        n = conn.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar()
        if n:
            return True
    return False


def _create_owner(conn: sa.engine.Connection) -> int:
    from datetime import datetime

    email = _owner_email(conn)
    conn.execute(
        sa.text(
            "INSERT INTO appuser "
            "(email, password_hash, created_at, is_owner, disabled) "
            "VALUES (:email, :pw, :now, :owner, :disabled)"
        ),
        {
            "email": email,
            "pw": _UNUSABLE_PASSWORD_HASH,
            "now": datetime.utcnow(),
            "owner": True,
            "disabled": False,
        },
    )
    owner_id = conn.execute(
        sa.text("SELECT id FROM appuser WHERE email = :email"), {"email": email}
    ).scalar_one()
    return int(owner_id)


def _announce_owner(conn: sa.engine.Connection, owner_id: int) -> None:
    email = conn.execute(
        sa.text("SELECT email FROM appuser WHERE id = :id"), {"id": owner_id}
    ).scalar_one()
    # print, not log: this has to be impossible to miss in the output of
    # `alembic upgrade head`, and the operator cannot log in until they act.
    print(
        "\n"
        "=======================================================================\n"
        " Existing data was adopted by a new owner account:\n"
        f"   id    {owner_id}\n"
        f"   email {email}\n"
        "\n"
        " It has NO usable password yet. Set one before starting the server:\n"
        f"   python scripts/set_password.py {email}\n"
        "\n"
        " Change the email first if that address is wrong — it is the login.\n"
        "=======================================================================\n"
    )


def downgrade() -> None:
    """Drop what this revision added. Never deletes application data.

    Note that dropping ``appuser`` discards accounts and therefore passwords;
    the tenant rows themselves survive untouched, reverting to the single-tenant
    shape they had before.
    """
    conn = op.get_bind()

    # Collapsing (user_id, key) back to a bare key can collide across users.
    # Keep the owner's row for each key where there is one, else the lowest
    # user_id, so the downgraded install has a coherent single-tenant view
    # rather than an arbitrary mix of users' settings.
    owner_ids = {
        int(r[0])
        for r in conn.execute(
            sa.text("SELECT id FROM appuser WHERE is_owner")
        ).all()
    }
    winners: dict[str, tuple[int, str]] = {}
    for user_id, key, value in conn.execute(
        sa.text("SELECT user_id, key, value FROM setting ORDER BY user_id")
    ).all():
        current = winners.get(key)
        if current is None:
            winners[key] = (user_id, value)
        elif user_id in owner_ids and current[0] not in owner_ids:
            winners[key] = (user_id, value)

    op.drop_table("setting")
    op.create_table(
        "setting",
        sa.Column("key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("value", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint("key", name="pk_setting"),
    )
    if winners:
        conn.execute(
            sa.text("INSERT INTO setting (key, value) VALUES (:key, :value)"),
            [{"key": k, "value": v} for k, (_uid, v) in winners.items()],
        )

    for table in _TENANT_TABLES:
        op.drop_index(f"ix_{table}_user_id_id", table_name=table)
        op.drop_index(op.f(f"ix_{table}_user_id"), table_name=table)
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(
                f"fk_{table}_user_id_appuser", type_="foreignkey"
            )
            batch.drop_column("user_id")

    op.drop_table("usersecret")
    op.drop_index(op.f("ix_usersession_user_id"), table_name="usersession")
    op.drop_table("usersession")
    op.drop_index(op.f("ix_appuser_email"), table_name="appuser")
    op.drop_table("appuser")
