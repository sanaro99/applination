"use client";
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { batchPriceLabel, type BatchRoute, type ExecutionMode } from '@/lib/batch-run';

export function BatchRunOptions({ mode, route, onMode, onRoute }: {
  mode: ExecutionMode; route: BatchRoute; onMode: (mode: ExecutionMode) => void; onRoute: (route: BatchRoute) => void;
}) {
  const { data, isLoading, error } = useQuery({ queryKey: ['batch-capabilities'],
    queryFn: api.batchCapabilities, enabled: mode === 'batch' });
  const selected = data?.find(r => r.provider === route.provider && r.model === route.model);
  return <div className="space-y-3 rounded-lg border p-4">
    <label className="block space-y-1 text-sm">
      <span className="font-medium">Processing mode</span>
      <select className="w-full rounded border bg-background p-2" value={mode}
        onChange={e => onMode(e.target.value as ExecutionMode)}>
        <option value="immediate">Immediate — current provider settings</option>
        <option value="batch">Lower cost — asynchronous batches</option>
      </select>
    </label>
    {mode === 'batch' && <>
      <p className="text-sm text-muted-foreground">Eligible AI tokens cost 50% of standard pricing. Each dependent round can take up to 24 hours; the full run may take longer. Ordinary calls keep their current settings.</p>
      <label className="block space-y-1 text-sm"><span className="font-medium">Batch provider and model</span>
        <select className="w-full rounded border bg-background p-2" value={`${route.provider}:${route.model}`}
          onChange={e => { const [provider, model] = e.target.value.split(':'); onRoute({ provider, model }); }}>
          {!data && <option value={`${route.provider}:${route.model}`}>Loading models…</option>}
          {data?.map(r => <option key={`${r.provider}:${r.model}`} value={`${r.provider}:${r.model}`}>
            {r.provider} / {r.model}{r.configured ? '' : ' — API key needed'}
          </option>)}
        </select>
      </label>
      <p className="text-xs text-muted-foreground">{selected && batchPriceLabel(selected.input_per_million, selected.output_per_million)}</p>
      {selected && !selected.configured && <p className="text-sm text-amber-600">Add your API key in Providers before starting.</p>}
      {isLoading && <p className="text-sm">Checking supported batch routes…</p>}
      {error && <p className="text-sm text-destructive">Could not load supported batch routes.</p>}
      <p className="text-xs text-muted-foreground">This selection applies only to this batch run. Failed items pause for review; full-price completion requires a separate confirmation.</p>
    </>}
  </div>;
}
