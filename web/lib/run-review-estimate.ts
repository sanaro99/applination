import type { BatchRoute } from './batch-run';
import { estimateRun, type RunEstimate } from './cost-estimate';
import type { LlmConfig, PricingWindow } from './types';

// Native standard uncached text-token USD/1M, checked 2026-10-01.
// Short-context global paid tier, excluding tools, taxes and regional premiums.
export const PRICE_SOURCES: Record<string, string> = {
  openai: 'https://developers.openai.com/api/docs/pricing',
  claude: 'https://platform.claude.com/docs/en/about-claude/pricing',
  gemini: 'https://ai.google.dev/gemini-api/docs/pricing',
};
const RATES: Record<string, Record<string, [number, number]>> = {
  openai: { 'gpt-6-luna': [.1, .5], 'gpt-6-sol': [2, 10], 'gpt-5.6-luna': [.2, 1.2] },
  claude: { 'claude-haiku-4-5': [1, 5], 'claude-sonnet-4-6': [3, 15],
    'claude-opus-4-6': [5, 25], 'claude-sonnet-5-5': [2, 10] },
  gemini: { 'gemini-2.5-flash': [.3, 2.5], 'gemini-2.5-flash-lite': [.1, .4], 'gemini-2.5-pro': [1.25, 10] },
};
export function batchTokenRates(route: BatchRoute): [number, number] | undefined {
  const rates = RATES[route.provider]?.[route.model];
  return rates && [rates[0] / 2, rates[1] / 2];
}

// Planning allowances, not measured usage or a spending cap. Ranking covers a
// fetched pool independent of selected count. Per-job allowances include writing,
// validation/repair and optional premium/critique/answer stages conservatively:
// routing alone does not reveal which jobs need them. No AI call estimates cost.
const WORKLOAD: Record<string, [number, number]> = {
  ranking: [100_000, 10_000], tailoring: [20_000, 4_000], tailoring_premium: [8_000, 2_000],
  cover_letter: [6_000, 1_000], critique: [4_000, 500], answer_questions: [4_000, 1_000],
};
export function estimateReview(count: number, opts?: {
  dryRun?: boolean; llmConfig?: LlmConfig; pricing?: PricingWindow; batchRoute?: BatchRoute;
}): RunEstimate & { models: string[] } {
  const ordinary = estimateRun(count, opts);
  const tasks = opts?.dryRun ? ['ranking'] : Object.keys(WORKLOAD);
  const cfg = opts?.llmConfig;
  const models = new Set<string>();
  let usd = 0;
  let known = true;
  let allDeepSeekFlash = !opts?.batchRoute && !!cfg;
  for (const task of tasks) {
    const provider = opts?.batchRoute?.provider ?? cfg?.tasks[task]?.primary ?? cfg?.global.primary;
    const model = opts?.batchRoute?.model ?? (provider && (cfg?.tasks[task]?.models[provider]
      || cfg?.providers.find(p => p.name === provider)?.model));
    if (provider) models.add(`${provider} / ${model || 'model unavailable'}`);
    allDeepSeekFlash &&= provider === 'deepseek' && model === 'deepseek-flash';
    const rates = provider && model ? RATES[provider]?.[model] : undefined;
    if (!rates) { known = false; continue; }
    const [input, output] = WORKLOAD[task];
    usd += (input * rates[0] + output * rates[1]) * (task === 'ranking' ? 1 : count) / 1_000_000;
  }
  return { ...ordinary, models: [...models], peak: allDeepSeekFlash && ordinary.peak,
    usd: allDeepSeekFlash ? ordinary.usd : known ? usd * (opts?.batchRoute ? .5 : 1) : null };
}
