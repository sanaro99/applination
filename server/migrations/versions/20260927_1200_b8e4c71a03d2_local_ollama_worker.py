"""Outbound local Ollama worker credentials and pending model calls.

Revision ID: b8e4c71a03d2
Revises: d7b4e20a91c0
"""
from alembic import op
import sqlalchemy as sa

revision = "b8e4c71a03d2"
down_revision = "d7b4e20a91c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "localollamagrant",
        sa.Column("token_hash", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("appuser.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_localollamagrant_user_id", "localollamagrant", ["user_id"])
    op.create_table(
        "localollamatask",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("appuser.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("lease_hash", sa.String(), nullable=False),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_localollamatask_user_id", "localollamatask", ["user_id"])
    op.create_index("ix_localollamatask_status", "localollamatask", ["status"])


def downgrade() -> None:
    op.drop_index("ix_localollamatask_status", table_name="localollamatask")
    op.drop_index("ix_localollamatask_user_id", table_name="localollamatask")
    op.drop_table("localollamatask")
    op.drop_index("ix_localollamagrant_user_id", table_name="localollamagrant")
    op.drop_table("localollamagrant")
