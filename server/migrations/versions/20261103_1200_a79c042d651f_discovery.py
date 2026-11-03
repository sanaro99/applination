"""Add independent job discovery and generation queues."""
from alembic import op
import sqlalchemy as sa

revision = 'a79c042d651f'
down_revision = 'f31b90eac672'
branch_labels = depends_on = None


def upgrade():
    op.create_table('discoverysource',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('key', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False), sa.Column('params', sa.Text(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False), sa.Column('interval_seconds', sa.Integer(), nullable=False),
        sa.Column('next_due', sa.DateTime(), nullable=False), sa.Column('validators', sa.Text(), nullable=False),
        sa.Column('last_success', sa.DateTime()), sa.Column('last_error', sa.String(), nullable=False),
        sa.Column('failures', sa.Integer(), nullable=False), sa.Column('lease_token', sa.String(), nullable=False),
        sa.Column('lease_until', sa.DateTime()), sa.Column('budget_day', sa.String(), nullable=False),
        sa.Column('requests_used', sa.Integer(), nullable=False))
    op.create_index('ix_discoverysource_key', 'discoverysource', ['key'], unique=True)
    op.create_index('ix_discoverysource_next_due', 'discoverysource', ['next_due'])
    op.create_table('discoveredjob',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('source_id', sa.Integer(), sa.ForeignKey('discoverysource.id'), nullable=False),
        sa.Column('external_id', sa.String(), nullable=False), sa.Column('title', sa.String(), nullable=False),
        sa.Column('company', sa.String(), nullable=False), sa.Column('location', sa.String(), nullable=False),
        sa.Column('url', sa.String(), nullable=False), sa.Column('description', sa.Text(), nullable=False),
        sa.Column('remote', sa.Boolean(), nullable=False), sa.Column('employment_type', sa.String(), nullable=False),
        sa.Column('posted_at', sa.DateTime()), sa.Column('content_hash', sa.String(), nullable=False),
        sa.Column('first_seen', sa.DateTime(), nullable=False), sa.Column('last_seen', sa.DateTime(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False), sa.UniqueConstraint('source_id', 'external_id'))
    op.create_index('ix_discoveredjob_source_id', 'discoveredjob', ['source_id'])
    op.create_table('discoverysubscription',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('appuser.id'), primary_key=True),
        sa.Column('source_id', sa.Integer(), sa.ForeignKey('discoverysource.id'), primary_key=True))
    op.create_table('discoverystate',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('appuser.id'), primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False), sa.Column('fingerprint', sa.String(), nullable=False),
        sa.Column('last_matched', sa.DateTime()), sa.Column('error', sa.String(), nullable=False))
    op.create_table('jobmatch',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('user_id', sa.Integer(), sa.ForeignKey('appuser.id'), nullable=False),
        sa.Column('posting_id', sa.Integer(), sa.ForeignKey('discoveredjob.id'), nullable=False),
        sa.Column('score', sa.Integer(), nullable=False), sa.Column('reason', sa.String(), nullable=False),
        sa.Column('fingerprint', sa.String(), nullable=False), sa.Column('eligible', sa.Boolean(), nullable=False),
        sa.Column('saved', sa.Boolean(), nullable=False), sa.Column('dismissed', sa.Boolean(), nullable=False),
        sa.Column('applied', sa.Boolean(), nullable=False), sa.Column('application_id', sa.Integer(), sa.ForeignKey('application.id')),
        sa.UniqueConstraint('user_id', 'posting_id'))
    op.create_index('ix_jobmatch_user_id', 'jobmatch', ['user_id'])
    op.create_index('ix_jobmatch_posting_id', 'jobmatch', ['posting_id'])
    op.create_table('discoveryattempt',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('source_id', sa.Integer(), sa.ForeignKey('discoverysource.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('count', sa.Integer(), nullable=False),
        sa.Column('outcome', sa.String(), nullable=False))
    op.create_index('ix_discoveryattempt_source_id', 'discoveryattempt', ['source_id'])
    op.create_table('generationrequest',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('user_id', sa.Integer(), sa.ForeignKey('appuser.id'), nullable=False),
        sa.Column('match_id', sa.Integer(), sa.ForeignKey('jobmatch.id')), sa.Column('run_id', sa.Integer(), sa.ForeignKey('run.id'), nullable=False, unique=True),
        sa.Column('payload', sa.Text(), nullable=False), sa.Column('state', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('lease_token', sa.String(), nullable=False), sa.Column('lease_until', sa.DateTime()),
        sa.Column('error', sa.String(), nullable=False), sa.UniqueConstraint('user_id', 'match_id'))
    op.create_index('ix_generationrequest_user_id', 'generationrequest', ['user_id'])
    op.create_index('ix_generationrequest_state', 'generationrequest', ['state'])


def downgrade():
    for table in ('generationrequest', 'discoveryattempt', 'jobmatch', 'discoverystate', 'discoverysubscription', 'discoveredjob', 'discoverysource'):
        op.drop_table(table)
