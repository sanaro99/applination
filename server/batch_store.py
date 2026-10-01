"""Atomic durable claims: a waiting batch owns no pipeline worker thread."""
import json
from datetime import timedelta
from sqlalchemy import update, or_
from sqlmodel import select
from .db import BatchRunState, BatchJob, Run, session
from .time_utils import utc_now


def claim_run(run_id, user_id, worker_id):
    now = utc_now()
    with session() as s:
        result = s.execute(update(BatchRunState).where(
            BatchRunState.run_id == run_id, BatchRunState.user_id == user_id,
            or_(BatchRunState.lease_until == None, BatchRunState.lease_until < now),
        ).values(lease_owner=worker_id, lease_until=now + timedelta(seconds=120)))
        s.commit()
        return result.rowcount == 1


def renew_run(run_id, user_id, worker_id):
    with session() as s:
        result = s.execute(update(BatchRunState).where(
            BatchRunState.run_id == run_id, BatchRunState.user_id == user_id,
            BatchRunState.lease_owner == worker_id,
        ).values(lease_until=utc_now() + timedelta(seconds=120)))
        s.commit()
        return result.rowcount == 1


def release_run(run_id, user_id, worker_id):
    with session() as s:
        s.execute(update(BatchRunState).where(
            BatchRunState.run_id == run_id, BatchRunState.user_id == user_id,
            BatchRunState.lease_owner == worker_id,
        ).values(lease_owner='', lease_until=None))
        s.commit()


def load_state(run_id, user_id):
    with session() as s:
        row = s.exec(select(BatchRunState).where(
            BatchRunState.run_id == run_id, BatchRunState.user_id == user_id)).first()
        if row is None:
            raise LookupError('Batch run not found')
        return json.loads(row.payload)


def save_state(run_id, user_id, worker_id, state):
    with session() as s:
        result = s.execute(update(BatchRunState).where(
            BatchRunState.run_id == run_id, BatchRunState.user_id == user_id,
            BatchRunState.lease_owner == worker_id,
        ).values(payload=json.dumps(state, default=str)))
        if result.rowcount != 1:
            raise LookupError('Batch lease lost')
        s.commit()


def owned_jobs(run_id, user_id):
    with session() as s:
        rows = s.exec(select(BatchJob).where(BatchJob.run_id == run_id,
                                            BatchJob.user_id == user_id).order_by(BatchJob.id)).all()
        for row in rows:
            s.expunge(row)
        return rows
