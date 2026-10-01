import pytest
from src.batch.stages import ReplayProvider, PendingRequest, BatchFailure


def test_replay_preserves_payload_and_never_repeats_completed_call():
    transcript = {}
    p = ReplayProvider('openai', 'gpt-6-luna', 'ranking', 'group0', transcript)
    with pytest.raises(PendingRequest):
        p.json_call('system', 'prompt', 3000, schema={'type': 'object'})
    assert len(transcript) == 1
    key, entry = next(iter(transcript.items()))
    assert entry['request']['max_tokens'] == 3000
    assert entry['request']['system'] == 'system'
    assert entry['request']['schema'] == {'type': 'object'}
    entry.update(state='succeeded', content={'scores': []})
    p = ReplayProvider('openai', 'gpt-6-luna', 'ranking', 'group0', transcript)
    assert p.json_call('system', 'prompt', 3000, schema={'type': 'object'}) == {'scores': []}
    assert list(transcript) == [key]


def test_failed_batch_does_not_enter_ordinary_fallback():
    from src.providers.factory import try_chain
    transcript = {}
    p = ReplayProvider('claude', 'claude-haiku-4-5', 'tailoring', 'job0', transcript)
    with pytest.raises(PendingRequest):
        p.text_call('s', 'u')
    next(iter(transcript.values())).update(state='failed', error='expired')
    with pytest.raises(BatchFailure):
        try_chain([ReplayProvider('claude', 'claude-haiku-4-5', 'tailoring', 'job0', transcript)],
                  lambda p: p.text_call('s', 'u'), any_error=True)


def test_identity_includes_application_and_call_index():
    entries = {}
    for app in ('a', 'b'):
        p = ReplayProvider('openai', 'gpt-6-luna', 'cover_letter', app, entries)
        with pytest.raises(PendingRequest):
            p.text_call('s', 'u')
    assert len(entries) == 2
