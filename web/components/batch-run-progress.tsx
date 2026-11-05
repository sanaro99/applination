"use client";
import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { api } from '@/lib/api';
import { eligibleRecoveryItems } from '@/lib/batch-run';
import { Button } from '@/components/ui/button';

export function BatchRunProgress({ runId }: { runId: number }) {
  const client = useQueryClient();
  const { data, error } = useQuery({ queryKey: ['batch-run', runId], queryFn: () => api.batchStatus(runId),
    refetchInterval: query => ['queued', 'running', 'waiting'].includes(query.state.data?.status ?? '') ? 15000 : false });
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<{preview_token: string; notice: string; action: string; item_ids: string[]} | null>(null);
  const [providerId, setProviderId] = useState('');
  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    try {
      await fn();
      await Promise.all([client.invalidateQueries({queryKey: ['batch-run', runId]}),
        client.invalidateQueries({queryKey: ['run', runId]}), client.invalidateQueries({queryKey: ['runs']})]);
    } catch (e) { toast.error(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  if (error) return <p className="text-sm text-destructive">Unable to load batch progress.</p>;
  if (!data) return <p className="text-sm">Loading batch progress…</p>;
  const failed = new Set(eligibleRecoveryItems(data.items));
  const chosen = selected.filter(id => failed.has(id));
  const terminal = ['done', 'cancelled'].includes(data.status);
  return <section className="space-y-3 rounded-lg border p-4" aria-label="Batch progress">
    <h2 className="font-medium">Discounted batch run — {data.status.replaceAll('_', ' ')}</h2>
    <p className="text-sm">{data.counts.succeeded ?? 0} AI requests completed · {data.counts.waiting ?? 0} waiting · {data.counts.failed ?? 0} failed</p>
    <p className="text-sm text-muted-foreground">The server resumes this run after results arrive. You can close this page. Each dependent batch round can take up to 24 hours.</p>
    {data.jobs.map(job => <div key={job.id} className="space-y-1 text-sm">
      <p>{job.provider} / {job.model} — {job.state.replaceAll('_', ' ')}</p>
      {job.next_poll_at && <p className="text-xs text-muted-foreground">Next status check: {new Date(job.next_poll_at).toLocaleString()}</p>}
      {job.error && <p className="text-amber-600">{job.error}</p>}
      {job.state === 'submission_unknown' && <div className="flex flex-wrap gap-2">
        <input className="rounded border bg-background p-2" aria-label="Provider batch ID" placeholder="Provider batch ID" value={providerId} onChange={e => setProviderId(e.target.value)} />
        <Button variant="outline" disabled={busy || !providerId} onClick={() => act(() => api.reconcileBatch(runId, job.id, providerId))}>Link completed provider batch</Button>
        <p className="w-full text-xs">Find the original batch in your provider console. Linking checks its completed request IDs and never creates a new batch.</p>
      </div>}
    </div>)}
    {data.items.filter(item => failed.has(item.id)).map(item => <label key={item.id} className="flex items-start gap-2 text-sm">
      <input type="checkbox" checked={chosen.includes(item.id)} onChange={e => { setPreview(null); setSelected(ids => e.target.checked ? [...ids, item.id] : ids.filter(id => id !== item.id)); }} />
      <span className="min-w-0">
        <span>{item.label ?? item.application_key ?? 'Ranking'} / {item.task}</span>
        {item.error && <span className="mt-1 block break-words text-xs text-destructive">{item.error}</span>}
      </span>
    </label>)}
    {!!chosen.length && <div className="flex flex-wrap gap-2">
      {['retry', 'complete-now'].map(action => <Button key={action} variant="outline" disabled={busy}
        onClick={() => act(async () => setPreview(await api.previewBatchRecovery(runId, chosen, action)))}>
        {action === 'retry' ? 'Review discounted retry' : 'Review full-price completion'}
      </Button>)}
    </div>}
    {preview && <div className="space-y-2 rounded border p-3 text-sm">
      <p>{preview.item_ids.length} selected requests. {preview.notice}</p>
      <Button disabled={busy} onClick={() => act(async () => {
        await api.confirmBatchRecovery(runId, preview.action, preview.preview_token);
        setPreview(null); setSelected([]);
      })}>Confirm {preview.action === 'retry' ? 'discounted retry' : 'standard-price completion'}</Button>
      <Button variant="ghost" onClick={() => setPreview(null)}>Dismiss</Button>
    </div>}
    {!terminal && <div className="flex flex-wrap gap-2">
      {data.status === 'batch_paused' && <Button variant="outline" disabled={busy} onClick={() => act(() => api.resumeBatch(runId))}>Resume status checks</Button>}
      <Button variant="outline" disabled={busy || data.cancel_requested} onClick={() => {
        if (window.confirm('Cancel pending batch work? Any unresolved submission will be abandoned locally and may still process or be billed at the provider. No replacement will be submitted.')) void act(() => api.cancelBatch(runId));
      }}>{data.cancel_requested ? 'Cancellation requested' : 'Cancel batch run'}</Button>
    </div>}
  </section>;
}
