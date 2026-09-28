"""Store each local Ollama worker's installed model inventory.

Revision ID: c62f8d9a04b1
Revises: b8e4c71a03d2
"""
from alembic import op
import sqlalchemy as sa

revision = "c62f8d9a04b1"
down_revision = "b8e4c71a03d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("localollamagrant", sa.Column("models_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("localollamagrant", "models_json")
