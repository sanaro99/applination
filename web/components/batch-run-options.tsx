"use client";
import { Clock, Coins, Zap } from 'lucide-react';
import { batchPriceLabel, type BatchCapability, type BatchRoute, type ExecutionMode } from '@/lib/batch-run';
import { batchTokenRates } from '@/lib/run-review-estimate';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

export function BatchRunOptions({ mode, route, onMode, onRoute, capabilities, loading, failed }: {
  mode: ExecutionMode; route: BatchRoute; onMode: (mode: ExecutionMode) => void; onRoute: (route: BatchRoute) => void;
  capabilities?: BatchCapability[]; loading: boolean; failed: boolean;
}) {
  const selected = capabilities?.find(r => r.provider === route.provider && r.model === route.model);
  const rates = batchTokenRates(route);
  const items = capabilities?.map(r => ({ value: `${r.provider}:${r.model}`, label: `${r.provider} / ${r.model}` })) ?? [];
  return <div className="space-y-4">
    <fieldset className="space-y-2">
      <legend className="mb-2 text-sm font-medium">How would you like to run?</legend>
      <div className="grid gap-3 sm:grid-cols-2">
        {([{value:'immediate', title:'Immediate', detail:'Use your current provider settings.', icon:Zap},
           {value:'batch', title:'Lower cost', detail:'50% off eligible tokens. Up to 24h per round.', icon:Coins}] as const).map(option => (
          <label key={option.value} className="relative cursor-pointer">
            <input className="peer sr-only" type="radio" name="execution-mode" value={option.value}
              checked={mode === option.value} onChange={() => onMode(option.value)} />
            <span className="flex h-full flex-col gap-2 rounded-xl border border-border bg-card p-4 transition-colors hover:bg-accent/50 peer-checked:border-primary peer-checked:bg-primary/5 peer-checked:ring-1 peer-checked:ring-primary peer-focus-visible:ring-3 peer-focus-visible:ring-ring/50">
              <span className="flex items-center gap-2 font-medium"><option.icon className="size-4 text-primary" />{option.title}</span>
              <span className="text-xs leading-relaxed text-muted-foreground">{option.detail}</span>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
    {mode === 'batch' && <div className="space-y-2">
      <label id="batch-model-label" className="text-sm font-medium">Batch provider and model</label>
      <Select items={items} value={`${route.provider}:${route.model}`} disabled={loading || failed}
        onValueChange={value => { if (value) { const [provider, model] = value.split(':'); onRoute({provider, model}); } }}>
        <SelectTrigger aria-labelledby="batch-model-label" className="w-full"><SelectValue placeholder="Choose a batch model" /></SelectTrigger>
        <SelectContent alignItemWithTrigger={false}>{items.map(item => <SelectItem key={item.value} value={item.value}>
          {item.label}{capabilities?.find(r => `${r.provider}:${r.model}` === item.value)?.configured ? '' : ' — API key needed'}
        </SelectItem>)}</SelectContent>
      </Select>
      {selected && <p className="text-xs text-muted-foreground">{batchPriceLabel(rates?.[0] ?? selected.input_per_million, rates?.[1] ?? selected.output_per_million)}</p>}
      {selected && !selected.configured && <p className="text-sm text-amber-600 dark:text-amber-400">Add your API key in Providers before starting.</p>}
      {route.provider === 'openai' && <p className="text-xs text-muted-foreground">Reasoning counts toward output tokens. The estimate includes extra room for batch reasoning; ordinary call limits stay unchanged.</p>}
      {loading && <p className="text-xs text-muted-foreground">Checking supported batch models…</p>}
      {failed && <p className="text-sm text-destructive">Could not load batch models. Reopen review to retry.</p>}
      <p className="flex gap-1.5 text-xs text-muted-foreground"><Clock className="mt-0.5 size-3 shrink-0" />Dependent rounds can make the full run take longer than 24 hours. Failed items pause for review.</p>
    </div>}
  </div>;
}
