from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import json
from datetime import timedelta
import yaml
from sqlmodel import select
from server import db
from server.db import Run, RunStatus, BatchRunState, BatchJob, User, Application
from server.time_utils import utc_now
from .conftest import make_engine


def test_full_batch_run_uses_original_generation_validators_and_survives_ticks(tmp_path, monkeypatch):
    from server import batch_runs as br
    from src.batch.workflow import ReplayTailor
    from src.batch.stages import PendingRequest
    from src.providers.demo_provider import DemoProvider
    from src.master_resume import load_master
    from src.reference_loader import load_stories
    from src.scrapers import Job
    root = Path(__file__).resolve().parents[1]
    engine = make_engine(tmp_path)
    monkeypatch.setattr(db, 'engine', engine)
    with db.session() as s:
        user = User(email='e2e@example.com', password_hash='x')
        s.add(user); s.commit(); s.refresh(user)
        run = Run(user_id=user.id, execution_mode='batch', status=RunStatus.queued)
        s.add(run); s.commit(); s.refresh(run)
        s.add(BatchRunState(run_id=run.id, user_id=user.id)); s.commit()
        run_id, uid = run.id, user.id
    cfg = yaml.safe_load((root / 'demo_data/config.yaml').read_text(encoding='utf-8'))
    cfg['output']['produce_pdf'] = False
    cfg['llm']['critique_top_n'] = 0
    cfg['search']['max_jobs_per_day'] = 5
    cfg['search']['min_match_score'] = 0
    job = Job('test', 'Target Infrastructure', 'Backend Reliability Engineer', 'Remote',
              'https://example.test/job', 'Own Python data services, retries, observability, and on-call reliability.')
    routes = {task: dict(provider='openai', model='gpt-6-luna', thinking='off') for task in br.TASKS}
    snap = dict(version=1, cfg=cfg, master=load_master(root / 'demo_data/master_data/resume.yaml'),
        stories=load_stories(root / 'demo_data/master_data/stories'), examples=[], guidelines=[],
        bio='I care about reliable systems and understanding failure modes.', jobs=[asdict(job)],
        excluded=[], routes=routes, transcript={}, applications={}, day='2026-10-01', dry_run=False, no_cache=True)
    monkeypatch.setattr(br, '_snapshot', lambda run: deepcopy(snap))
    submissions, responses = [], {}
    demo = DemoProvider(delay=(0, 0))
    def response(r):
        required = set((r.get('schema') or {}).get('required') or [])
        if 'selected_experience' in required:
            from src.evidence import build_evidence_ledger, default_content_plan
            return default_content_plan(snap['master'], asdict(job), build_evidence_ledger(snap['master'], snap['stories']))
        if 'verdicts' in required:
            import re
            claims = json.loads(r['user'].split('):\n', 1)[1].split('\n\nAudit every', 1)[0])
            ids = re.findall(r'^\[([^\]]+)\]', r['user'], re.MULTILINE)
            return {'passed': True, 'verdicts': [dict(path=c['path'], claim=c['text'][:100],
                support='direct', evidence_ids=ids, action='accept', reason='Mocked supported verdict') for c in claims]}
        return (demo.json_call(r['system'], r['user'], r['max_tokens'], schema=r['schema']) if r['json_mode']
                else demo.text_call(r['system'], r['user'], r['max_tokens']))
    class Adapter:
        def submit(self, requests, key):
            submissions.append([r['request_id'] for r in requests])
            provider_id = f'batch_{len(submissions)}'
            responses[provider_id] = [dict(request_id=r['request_id'], state='succeeded', error=None, usage={'input_tokens': 12},
                content=response(r)) for r in requests]
            return provider_id
        def status(self, provider_id):
            return 'completed'
        def results(self, provider_id):
            return list(reversed(responses[provider_id]))
        def cleanup(self, provider_id):
            pass
    monkeypatch.setattr(br, 'adapter_for', lambda *args: Adapter())
    # SSE is optional; shutdown or a disconnected loop must not pause persisted work.
    def closed_notification_loop(*args, **kwargs):
        raise RuntimeError('Event loop is closed')
    monkeypatch.setattr(br.bus, 'publish_threadsafe', closed_notification_loop)
    original_set_run = br._set_run
    def report_failure(run_id, user_id, status, **fields):
        if status == RunStatus.batch_paused:
            import sys
            raise AssertionError(fields.get('error')) from sys.exception()
        return original_set_run(run_id, user_id, status, **fields)
    monkeypatch.setattr(br, '_set_run', report_failure)
    for tick in range(12):
        br.advance_batch_run(run_id, uid)
        with db.session() as s:
            current = s.get(Run, run_id)
            if current.status in (RunStatus.done, RunStatus.partial_failed, RunStatus.batch_paused):
                break
            for batch in s.exec(select(BatchJob)).all():
                batch.next_poll_at = utc_now() - timedelta(seconds=1)
                s.add(batch)
            s.commit()
    with db.session() as s:
        current = s.get(Run, run_id)
        state = json.loads(s.get(BatchRunState, run_id).payload)
        assert current.status == RunStatus.done, (current.error, state.get('applications'))
        apps = s.exec(select(Application)).all()
        assert len(apps) == 1
        folder = Path(apps[0].folder_path)
        assert (folder / 'resume.docx').exists()
        assert (folder / 'cover_letter.docx').exists()
        audit = json.loads((folder / 'grounding_audit.json').read_text())
        assert audit['final_grounding']['passed']
    all_requests = [key for group in submissions for key in group]
    assert len(all_requests) == len(set(all_requests))
    before = len(submissions)
    br.advance_batch_run(run_id, uid)
    assert len(submissions) == before
    with db.session() as s:
        assert len(s.exec(select(Application)).all()) == 1
