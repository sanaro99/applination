import { describe, expect, it } from 'vitest';
import { estimateReview } from './run-review-estimate';
import type { LlmConfig } from './types';

function config(model = 'gpt-6-luna'): LlmConfig {
  return { global: { primary: 'openai', fallbacks: [] }, tasks: {}, task_names: [],
    providers: [{ name: 'openai', model, configured: true, role: 'primary', account_id: '' }] };
}

describe('review estimate follows selected routes', () => {
  it('uses the current model and changes when the configured model changes', () => {
    const luna = estimateReview(10, { llmConfig: config() });
    const sol = estimateReview(10, { llmConfig: config('gpt-6-sol') });
    expect(luna.usd).toBeGreaterThan(0);
    expect(sol.usd!).toBeGreaterThan(luna.usd!);
    expect(luna.models).toEqual(['openai / gpt-6-luna']);
  });
  it('discounts the same model, rather than halving a different current provider estimate', () => {
    const immediate = estimateReview(10, { llmConfig: config() });
    const batch = estimateReview(10, { batchRoute: { provider: 'openai', model: 'gpt-6-luna', thinking: 'off' } });
    expect(batch.usd).toBeCloseTo(immediate.usd! / 2);
    expect(batch.peak).toBe(false);
    expect(estimateReview(30, { batchRoute: { provider: 'openai', model: 'gpt-6-luna' } }).usd!).toBeGreaterThan(batch.usd!);
  });
  it('includes batch reasoning room without changing ordinary estimates', () => {
    const route = {provider: 'openai', model: 'gpt-6-luna'};
    const base = estimateReview(10, {batchRoute: {...route, thinking:'off'}});
    const reasoning = estimateReview(10, {batchRoute: route});
    expect(reasoning.usd!).toBeGreaterThan(base.usd!);
    expect(estimateReview(10, {batchRoute: route, dryRun:true}).usd)
      .toEqual(estimateReview(10, {batchRoute: {...route, thinking:'off'}, dryRun:true}).usd);
    expect(estimateReview(10, {llmConfig:config()}).usd).toBeCloseTo(base.usd! * 2);
  });
  it('honors task-specific model overrides and unknown routes', () => {
    const cfg = config();
    cfg.tasks.cover_letter = { primary: 'openai', models: {openai: 'gpt-6-sol'}, fallbacks: [], thinking: null };
    expect(estimateReview(10, {llmConfig:cfg}).usd!).toBeGreaterThan(estimateReview(10, {llmConfig:config()}).usd!);
    cfg.tasks.cover_letter.models.openai = 'custom-unpriced';
    expect(estimateReview(10, {llmConfig:cfg}).usd).toBeNull();
    expect(estimateReview(10, {llmConfig:cfg, dryRun:true}).usd).not.toBeNull();
    expect(estimateReview(10).usd).toBeNull();
  });
  it('dry runs only estimate ranking and never tailoring', () => {
    const route = { provider:'claude', model:'claude-haiku-4-5' };
    expect(estimateReview(5, {batchRoute:route, dryRun:true}).usd).toEqual(estimateReview(30, {batchRoute:route, dryRun:true}).usd);
    expect(estimateReview(10, {batchRoute:{provider:'gemini',model:'gemini-2.5-flash'}}).usd).not.toBeNull();
    expect(estimateReview(10, {batchRoute:{provider:'openrouter',model:'gpt-6-luna'}}).usd).toBeNull();
  });
  it('does not quote Flash prices or peak scheduling for a different DeepSeek model', () => {
    const cfg = config();
    cfg.global.primary = 'deepseek';
    cfg.providers = [{name:'deepseek', model:'custom-deepseek-model', configured:true, role:'primary', account_id:''}];
    expect(estimateReview(10, {llmConfig:cfg, pricing:{avoid_peak:true, peak:true, next_non_peak_utc:'2026-10-02', windows:[]}}))
      .toMatchObject({usd:null, peak:false});
  });
});
