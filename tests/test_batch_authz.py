import json
import pytest
from fastapi.testclient import TestClient
from server import db
from server.db import Run, RunStatus, BatchRunState
from .conftest import make_engine, register


def test_batch_routes_are_owner_only_and_recovery_excludes_completed(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, 'engine', engine)
    monkeypatch.setattr('server.batch_runs.dispatch_due_batches', lambda: 0)
    from server.app import app
    with TestClient(app) as a, TestClient(app) as b:
        ua, ub = register(a, 'a-batch@example.com'), register(b, 'b-batch@example.com')
        with db.session() as s:
            run = Run(user_id=ua['id'], execution_mode='batch', status=RunStatus.partial_failed)
            s.add(run); s.commit(); s.refresh(run)
            run_id = run.id
            entry = dict(provider='openai', application_key='job',
                request=dict(task='tailoring', model='gpt-6-luna', system='private', user='private',
                             max_tokens=3000, thinking='off', schema=None, json_mode=True))
            s.add(BatchRunState(run_id=run.id, user_id=ua['id'], payload=json.dumps(dict(version=1,
                transcript={'done': {**entry, 'state':'succeeded', 'content':{}}, 'failed': {**entry, 'state':'failed', 'error':'Invalid schema: missing location'}},
                applications={}))))
            s.commit()
        assert b.get(f'/api/runs/{run_id}/batch').status_code == 404
        for action in ('retry', 'complete-now', 'cancel', 'resume', 'preview', 'reconcile'):
            body = {'preview_token':'x', 'item_ids':['failed'], 'action':'retry', 'job_id':1, 'provider_id':'batch_x'}
            assert b.post(f'/api/runs/{run_id}/batch/{action}', json=body).status_code == 404
        summary = a.get(f'/api/runs/{run_id}/batch')
        assert summary.status_code == 200
        assert 'private' not in summary.text
        assert next(i for i in summary.json()['items'] if i['id'] == 'failed')['error'] == 'Invalid schema: missing location'
        assert a.post(f'/api/runs/{run_id}/batch/preview', json={'item_ids':['done'], 'action':'retry'}).status_code == 409
        preview = a.post(f'/api/runs/{run_id}/batch/preview', json={'item_ids':['failed'], 'action':'retry'})
        assert preview.status_code == 200
        token = preview.json()['preview_token']
        assert a.post(f'/api/runs/{run_id}/batch/complete-now', json={'preview_token':token}).status_code == 409
        assert a.post(f'/api/runs/{run_id}/batch/retry', json={'preview_token':token}).status_code == 200
        assert a.post(f'/api/runs/{run_id}/batch/retry', json={'preview_token':token}).status_code == 409


def test_missing_key_before_immediate_recovery_is_still_retryable(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, 'engine', engine)
    monkeypatch.setattr('server.batch_runs.dispatch_due_batches', lambda: 0)
    from server.app import app
    def missing_key(*args, **kwargs):
        raise ValueError('missing key')
    monkeypatch.setattr('src.providers.factory.get_provider', missing_key)
    with TestClient(app) as client:
        user = register(client, 'missing-batch@example.com')
        with db.session() as s:
            run = Run(user_id=user['id'], execution_mode='batch', status=RunStatus.partial_failed)
            s.add(run); s.commit(); s.refresh(run)
            run_id = run.id
            entry = dict(provider='openai', state='failed', request=dict(model='gpt-6-luna', thinking='off'))
            s.add(BatchRunState(run_id=run_id, user_id=user['id'], payload=json.dumps(dict(
                version=1, transcript={'failed': entry}, applications={}))))
            s.commit()
        response = client.post(f'/api/runs/{run_id}/batch/preview', json={'item_ids':['failed'], 'action':'complete-now'})
        token = response.json()['preview_token']
        assert client.post(f'/api/runs/{run_id}/batch/complete-now', json={'preview_token':token}).status_code == 400
        with db.session() as s:
            state = json.loads(s.get(BatchRunState, run_id).payload)
            assert state['transcript']['failed']['state'] == 'failed'
        assert client.post(f'/api/runs/{run_id}/batch/preview', json={'item_ids':['failed'], 'action':'retry'}).status_code == 200
