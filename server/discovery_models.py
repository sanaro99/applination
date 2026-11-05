"""Discovery catalog, private feed state, and durable document requests."""
from datetime import datetime

from sqlalchemy import Text, UniqueConstraint
from sqlmodel import Field, SQLModel

from .time_utils import utc_now


class DiscoverySource(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(unique=True, index=True)
    kind: str
    params: str = Field(default='{}', sa_type=Text)
    # Public board sources are shared. Query sources carry an owner in their
    # key/params and are reachable only through that owner's subscriptions.
    enabled: bool = True
    interval_seconds: int = 600
    next_due: datetime = Field(default_factory=utc_now, index=True)
    validators: str = Field(default='{}', sa_type=Text)
    last_success: datetime | None = None
    last_error: str = ''
    failures: int = 0
    lease_token: str = ''
    lease_until: datetime | None = None
    budget_day: str = ''
    requests_used: int = 0


class DiscoveredJob(SQLModel, table=True):
    __table_args__ = (UniqueConstraint('source_id', 'external_id'),)
    id: int | None = Field(default=None, primary_key=True)
    source_id: int = Field(foreign_key='discoverysource.id', index=True)
    external_id: str
    title: str
    company: str
    location: str = ''
    url: str
    description: str = Field(default='', sa_type=Text)
    remote: bool = False
    employment_type: str = ''
    posted_at: datetime | None = None
    content_hash: str = ''
    first_seen: datetime = Field(default_factory=utc_now)
    last_seen: datetime = Field(default_factory=utc_now)
    active: bool = True


class DiscoverySubscription(SQLModel, table=True):
    user_id: int = Field(foreign_key='appuser.id', primary_key=True)
    source_id: int = Field(foreign_key='discoverysource.id', primary_key=True)


class DiscoveryState(SQLModel, table=True):
    user_id: int = Field(foreign_key='appuser.id', primary_key=True)
    enabled: bool = True
    fingerprint: str = ''
    last_matched: datetime | None = None
    error: str = ''


class JobMatch(SQLModel, table=True):
    __table_args__ = (UniqueConstraint('user_id', 'posting_id'),)
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key='appuser.id', index=True)
    posting_id: int = Field(foreign_key='discoveredjob.id', index=True)
    score: int = 0
    reason: str = ''
    fingerprint: str = ''
    eligible: bool = True
    saved: bool = False
    dismissed: bool = False
    applied: bool = False
    application_id: int | None = Field(default=None, foreign_key='application.id')


class DiscoveryAttempt(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    source_id: int = Field(foreign_key='discoverysource.id', index=True)
    created_at: datetime = Field(default_factory=utc_now)
    count: int = 0
    outcome: str = ''


class GenerationRequest(SQLModel, table=True):
    __table_args__ = (UniqueConstraint('user_id', 'match_id'),)
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key='appuser.id', index=True)
    match_id: int | None = Field(default=None, foreign_key='jobmatch.id')
    run_id: int = Field(foreign_key='run.id', unique=True)
    payload: str = Field(sa_type=Text)
    state: str = Field(default='queued', index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    lease_token: str = ''
    lease_until: datetime | None = None
    error: str = ''
