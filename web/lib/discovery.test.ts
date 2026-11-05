import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from './api';
import { isRunActive } from './use-latest-runs';

afterEach(() => vi.unstubAllGlobals());

describe('continuous discovery contract', () => {
  it('does not treat historical provider batches as workspace activity', () => {
    for (const status of ['waiting', 'batch_paused', 'partial_failed'] as const) expect(isRunActive(status)).toBe(false);
    expect(isRunActive('running')).toBe(true);
  });
  it('reads the stored feed and only generates a selected job', async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [] }) });
    vi.stubGlobal('fetch', fetch);
    await api.listJobs({ q: 'data & ML', view: 'saved', sort: 'newest', remote: true, offset: 30 });
    expect(fetch.mock.calls[0][0]).toContain('/api/jobs?');
    expect(fetch.mock.calls[0][0]).toContain('q=data+%26+ML');
    await api.generateJob(42);
    expect(fetch.mock.calls[1][0]).toContain('/api/jobs/42/generate');
    expect(fetch.mock.calls[1][1].method).toBe('POST');
  });
});
