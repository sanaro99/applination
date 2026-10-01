"""Atomic durable claims: a waiting batch owns no pipeline worker thread."""
import json
import threading
from datetime import timedelta
from sqlalchemy import update, or_
from sqlmodel import select
from .db import BatchRunState, BatchJob, Run, session
from .time_utils import utc_now
from .scoping import owned


def start_heartbeat(run_id, user_id, worker_id):
    stop = threading.Event()
    def heartbeat():
        while not stop.wait(30):
            try:
                if not renew_run(run_id, user_id, worker_id):
                    return
            except Exception:
                return
    threading.Thread(target=heartbeat, daemon=True).start()
    return stop


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
        row = s.exec(owned(select(BatchRunState).where(
            BatchRunState.run_id == run_id), BatchRunState, user_id)).first()
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


def begin_submission(job_id, run_id, user_id, worker_id):
    """Atomically fence stale workers before the durable billable boundary.

    Updating the lease row takes the same database lock as claim_run. A worker
    cannot resurrect a prepared job that a new lease holder superseded.
    """
    now = utc_now()
    with session() as s:
        lease = s.execute(update(BatchRunState).where(
            BatchRunState.run_id == run_id, BatchRunState.user_id == user_id,
            BatchRunState.lease_owner == worker_id, BatchRunState.lease_until >= now,
        ).values(lease_until=now + timedelta(seconds=120)))
        if lease.rowcount != 1:
            raise LookupError('Batch lease lost before submission boundary')
        job = s.execute(update(BatchJob).where(
            BatchJob.id == job_id, BatchJob.run_id == run_id, BatchJob.user_id == user_id,
            BatchJob.state == 'prepared',
        ).values(state='submitting'))
        if job.rowcount != 1:
            raise LookupError('Batch job already superseded or submitted')
        s.commit()


def owned_jobs(run_id, user_id):
    with session() as s:
        rows = s.exec(owned(select(BatchJob).where(BatchJob.run_id == run_id).order_by(BatchJob.id),
                            BatchJob, user_id)).all()
        for row in rows:
            s.expunge(row)
        return rows
