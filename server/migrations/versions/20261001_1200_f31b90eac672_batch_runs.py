"""Add opt-in durable batch runs; ordinary runs remain immediate."""
from alembic import op
import sqlalchemy as sa

revision = 'f31b90eac672'
down_revision = 'ea24b87516d3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('application', sa.Column('batch_item_key', sa.String(), nullable=True))
    op.create_index('ix_application_batch_item_key', 'application', ['batch_item_key'], unique=True)
    op.add_column('run', sa.Column('execution_mode', sa.String(), nullable=False, server_default='immediate'))
    op.add_column('run', sa.Column('batch_routes', sa.Text(), nullable=False, server_default='{}'))
    op.create_table('batchrunstate',
        sa.Column('run_id', sa.Integer(), sa.ForeignKey('run.id'), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('appuser.id'), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('lease_owner', sa.String(), nullable=False, server_default=''),
        sa.Column('lease_until', sa.DateTime(timezone=True)),
        sa.Column('next_poll_at', sa.DateTime(timezone=True)))
    op.create_index('ix_batchrunstate_user_id', 'batchrunstate', ['user_id'])
    op.create_table('batchjob',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('run_id', sa.Integer(), sa.ForeignKey('run.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('appuser.id'), nullable=False),
        sa.Column('provider', sa.String(), nullable=False), sa.Column('model', sa.String(), nullable=False),
        sa.Column('state', sa.String(), nullable=False, server_default='prepared'),
        sa.Column('provider_id', sa.String()), sa.Column('request_ids', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('poll_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('next_poll_at', sa.DateTime(timezone=True)), sa.Column('error', sa.Text()))
    op.create_index('ix_batchjob_run_id', 'batchjob', ['run_id'])
    op.create_index('ix_batchjob_user_id', 'batchjob', ['user_id'])


def downgrade():
    op.drop_index('ix_application_batch_item_key', table_name='application')
    op.drop_column('application', 'batch_item_key')
    op.drop_table('batchjob')
    op.drop_table('batchrunstate')
    op.drop_column('run', 'batch_routes')
    op.drop_column('run', 'execution_mode')
