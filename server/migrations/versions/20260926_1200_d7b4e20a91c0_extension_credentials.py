"""Extension pairing and revocable credentials.

Revision ID: d7b4e20a91c0
Revises: a4e1f27c9b03
"""
from alembic import op
import sqlalchemy as sa

revision: str = "d7b4e20a91c0"
down_revision: str | None = "a4e1f27c9b03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "extensionpairing",
        sa.Column("device_hash", sa.String(), primary_key=True),
        sa.Column("user_code_hash", sa.String(), nullable=False),
        sa.Column("approved_user_id", sa.Integer(), sa.ForeignKey("appuser.id")),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_extensionpairing_user_code_hash", "extensionpairing", ["user_code_hash"], unique=True)
    op.create_table(
        "extensiongrant",
        sa.Column("token_hash", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("appuser.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_extensiongrant_user_id", "extensiongrant", ["user_id"])
    op.create_table(
        "extensiondocument",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("appuser.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("stored_name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_extensiondocument_user_id", "extensiondocument", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_extensiondocument_user_id", table_name="extensiondocument")
    op.drop_table("extensiondocument")
    op.drop_index("ix_extensiongrant_user_id", table_name="extensiongrant")
    op.drop_table("extensiongrant")
    op.drop_index("ix_extensionpairing_user_code_hash", table_name="extensionpairing")
    op.drop_table("extensionpairing")
