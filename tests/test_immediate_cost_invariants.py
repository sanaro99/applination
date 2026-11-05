from src.tailor import Tailor
from src.providers.base import LLMProvider


class RecordingProvider(LLMProvider):
    name = 'recording'
    def __init__(self):
        self.calls = []
    def text_call(self, system, user, max_tokens=1000):
        raise AssertionError('unexpected text call')
    def json_call(self, system, user, max_tokens=2000, *, schema=None):
        self.calls.append((system, user, max_tokens, schema))
        return {'scores': [{'idx': 0, 'score': 82, 'reason': 'match'}]}


def test_ordinary_ranking_call_count_and_token_budget():
    p = RecordingProvider()
    tailor = Tailor({'ranking': [p]})
    jobs = [{'company': 'a', 'title': 'b', 'desc': 'c'}] * 26
    tailor.rank_jobs(jobs, 'profile')
    assert len(p.calls) == 2
    assert [x[2] for x in p.calls] == [3000, 3000]
    assert all(x[3] is None for x in p.calls)
    assert '[24]' in p.calls[0][1] and '[1]' not in p.calls[1][1]


def test_old_run_requests_default_to_immediate():
    from server.runs import StartRunBody
    assert StartRunBody().execution_mode == 'immediate'
