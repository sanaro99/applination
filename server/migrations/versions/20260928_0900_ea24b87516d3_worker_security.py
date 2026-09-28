"""Replace indefinite worker keys with approved, expiring sessions.

Legacy grants have no session hash and are deliberately unusable after upgrade.
In-flight prompts from the previous protocol are cancelled and erased.
"""
from alembic import op
import sqlalchemy as sa

revision = "ea24b87516d3"
down_revision = "c62f8d9a04b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("pairing_expires_at", "approved_at", "expires_at"):
        op.add_column("localollamagrant", sa.Column(name, sa.DateTime(timezone=True), nullable=True))
    op.add_column("localollamagrant", sa.Column("session_hash", sa.String(), nullable=True))
    op.create_index("ix_localollamagrant_session_hash", "localollamagrant", ["session_hash"], unique=True)
    op.add_column("localollamatask", sa.Column("worker_grant_hash", sa.String(), nullable=True))
    op.create_index("ix_localollamatask_worker_grant_hash", "localollamatask", ["worker_grant_hash"])
    op.execute(sa.text(
        "UPDATE localollamatask SET status = 'error', payload = '', lease_hash = '', "
        "error = 'Worker security update requires pairing again' WHERE status IN ('pending', 'leased')"
    ))


def downgrade() -> None:
    # A downgrade must never turn a previously consumed pairing code into a key.
    op.execute(sa.text("DELETE FROM localollamagrant"))
    op.drop_index("ix_localollamatask_worker_grant_hash", table_name="localollamatask")
    op.drop_column("localollamatask", "worker_grant_hash")
    op.drop_index("ix_localollamagrant_session_hash", table_name="localollamagrant")
    op.drop_column("localollamagrant", "session_hash")
    for name in ("expires_at", "approved_at", "pairing_expires_at"):
        op.drop_column("localollamagrant", name)
