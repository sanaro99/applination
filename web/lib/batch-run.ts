export type ExecutionMode = 'immediate' | 'batch';
export type BatchRoute = { provider: string; model: string; thinking?: string };
export type BatchCapability = BatchRoute & {
  configured: boolean;
  input_per_million: number | null;
  output_per_million: number | null;
  verified_at: string;
};
export type BatchSummary = {
  status: string; cancel_requested: boolean;
  counts: Record<string, number>;
  items: { id: string; state: string; task: string; application_key?: string; label?: string }[];
  jobs: { id: number; provider: string; model: string; state: string;
    provider_id: string | null; next_poll_at: string | null; error: string | null }[];
};

export function batchRoutes(provider: string, model: string): Record<string, BatchRoute> {
  return Object.fromEntries(['ranking', 'tailoring', 'tailoring_premium', 'cover_letter', 'critique', 'answer_questions']
    .map(task => [task, { provider, model, thinking: task === 'ranking' ? 'off' : 'on' }]));
}
export function eligibleRecoveryItems(items: {id: string; state: string}[]): string[] {
  return items.filter(item => item.state === 'failed').map(item => item.id);
}
export function batchPriceLabel(input: number | null, output: number | null): string {
  return input == null || output == null ? 'Dollar estimate unknown; eligible tokens use 50% batch pricing.'
    : `$${input.toFixed(2)} input / $${output.toFixed(2)} output per million tokens (batch).`;
}
