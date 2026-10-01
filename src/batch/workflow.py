"""Run the existing generation methods against a persisted response transcript."""
from dataclasses import asdict
from datetime import datetime
import logging
from src.tailor import Tailor
from src.scrapers import Job
from src.profile import derive_profile
from src.reference_loader import match_stories, match_guidelines, match_example_letter
from .stages import replay_chains, PendingRequest, BatchFailure

LOG = logging.getLogger(__name__)


class ReplayTailor(Tailor):
    def __init__(self, routes, application_key, transcript):
        self.routes, self.application_key, self.transcript = routes, application_key, transcript
        super().__init__(replay_chains(routes, application_key, transcript))

    def _operation(self, name, fn, *args, **kwargs):
        self._chains = replay_chains(self.routes, self.application_key + ':' + name, self.transcript)
        return fn(*args, **kwargs)

    def rank_jobs(self, *args, **kwargs):
        jobs, profile = args
        scored, pending = [], False
        for start in range(0, len(jobs), 25):
            try:
                part = self._operation(f'ranking-{start}', super().rank_jobs, jobs[start:start + 25], profile)
                if len(part) != len(jobs[start:start + 25]) or any(s.get('reason') in ('(rank failed)', '(parse failed)') for s in part):
                    raise BatchFailure('Invalid ranking response; review before retrying.')
                scored.extend({**s, 'idx': s['idx'] + start} for s in part)
            except PendingRequest:
                pending = True
        if pending:
            raise PendingRequest('Ranking groups pending')
        return scored

    def tailor_resume(self, *args, **kwargs):
        return self._operation('resume', super().tailor_resume, *args, **kwargs)

    def write_cover_letter(self, *args, **kwargs):
        return self._operation('letter', super().write_cover_letter, *args, **kwargs)

    def answer_questions(self, *args, **kwargs):
        return self._operation('answers', super().answer_questions, *args, **kwargs)


def job_from_dict(raw):
    raw = dict(raw)
    if isinstance(raw.get('posted_at'), str):
        raw['posted_at'] = datetime.fromisoformat(raw['posted_at']) if raw['posted_at'] else None
    return Job(**raw)


def prepare_generation(state):
    """Advance every independent application operation to its next network boundary."""
    for key, app in state['applications'].items():
        if app.get('published') or app.get('cached'):
            continue
        job = job_from_dict(app['job'])
        jd = dict(company=job.company, title=job.title, location=job.location, description=job.description)
        stories = match_stories(job.description, job.company, job.title, state['stories'])
        guidelines = match_guidelines(job.description, job.title, state['guidelines'])
        example = match_example_letter(job.description, job.company, job.title, state['examples'])
        tailor = ReplayTailor(state['routes'], key, state['transcript'])
        operations = {
            'resume': lambda: tailor.tailor_resume(state['master'], jd, stories=stories,
                                                  guidelines=guidelines, quality_tier=app['quality_tier']),
            'letter': lambda: tailor.write_cover_letter(state['master'], jd, state['cfg']['user'],
                bio=state['bio'], stories=stories, example_letter=example, guidelines=guidelines,
                profile=derive_profile(state['master']), critique=app['critique']),
        }
        if job.additional_questions:
            operations['answers'] = lambda: tailor.answer_questions(job.additional_questions, jd,
                state['cfg']['user'], state['bio'], stories, specific_instructions=job.specific_instructions,
                master=state['master'], profile=derive_profile(state['master']))
        for name, operation in operations.items():
            if app.get(name) == 'ready':
                continue
            try:
                value = operation()
                from src.tailor import COVER_LETTER_FAILURE_SENTINEL
                if name == 'letter' and (not value or str(value).startswith(COVER_LETTER_FAILURE_SENTINEL)):
                    raise ValueError('Cover letter did not pass validation')
                app[name] = 'ready'
                app.pop(name + '_error', None)
            except PendingRequest:
                app[name] = 'waiting'
            except (BatchFailure, Exception) as exc:
                app[name] = 'failed'
                app[name + '_error'] = str(exc)
        app['ready'] = all(app.get(name) == 'ready' for name in operations)


def prepare_ranking(state):
    from src.main import rank_and_filter, user_profile_blurb
    jobs = [job_from_dict(j) for j in state['jobs']]
    tailor = ReplayTailor(state['routes'], 'rank', state['transcript'])
    try:
        selected = rank_and_filter(jobs, state['cfg'], tailor,
            user_profile_blurb(state['master'], state['cfg']['user']), LOG,
            candidate_profile=derive_profile(state['master']), excluded_keys=set(state['excluded']))
    except PendingRequest:
        return False
    except BatchFailure as exc:
        state['ranking_error'] = str(exc)
        return False
    premium = int(state['cfg']['llm'].get('tailoring_premium_top_n', 0) or 0)
    critique_top = int(state['cfg']['llm'].get('critique_top_n', 0) or 0)
    state['applications'] = {job.dedupe_key(): {
        'job': asdict(job), 'quality_tier': 'premium' if i < premium else 'standard',
        'critique': bool(state['cfg']['llm'].get('critique_cover_letters') or i < critique_top),
    } for i, job in enumerate(selected)}
    state['ranked'] = [asdict(j) for j in jobs]
    state['ranking_done'] = True
    state.pop('ranking_error', None)
    return True
