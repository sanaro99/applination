import { describe, expect, it } from "vitest";

import { estimateRun } from "./cost-estimate";
import type { LlmConfig, PricingWindow } from "./types";

function config(primary: string): LlmConfig {
  return { global: { primary, fallbacks: [] }, tasks: {}, task_names: [], providers: [] };
}

const pricing: PricingWindow = {
  avoid_peak: true, peak: true, next_non_peak_utc: "2026-10-01T16:00:00Z", windows: [],
};

describe("provider-aware run estimates", () => {
  it.each(["ollama", "openai", "gemini", "claude", "openrouter"])(
    "does not apply DeepSeek pricing or peak scheduling to %s", (primary) => {
      const estimate = estimateRun(10, { llmConfig: config(primary), pricing });
      expect(estimate.usd).toBeNull();
      expect(estimate.peak).toBe(false);
      expect(estimate.minutes).toBeGreaterThan(0);
    },
  );

  it("withholds provider pricing while routing is unavailable", () => {
    expect(estimateRun(10, { pricing })).toMatchObject({ usd: null, peak: false });
  });

  it("retains DeepSeek's estimate and scheduling at peak", () => {
    expect(estimateRun(10, { llmConfig: config("deepseek"), pricing }))
      .toMatchObject({ usd: 0.16, peak: true });
  });

  it("does not offer peak scheduling outside enabled peak windows", () => {
    for (const window of [{ ...pricing, peak: false }, { ...pricing, avoid_peak: false }]) {
      expect(estimateRun(10, { llmConfig: config("deepseek"), pricing: window }))
        .toMatchObject({ usd: 0.08, peak: false });
    }
  });

  it("withholds a DeepSeek total for mixed pipeline task providers", () => {
    const llmConfig = config("deepseek");
    llmConfig.tasks.tailoring = { primary: "ollama", fallbacks: [], models: {}, thinking: null };
    expect(estimateRun(10, { llmConfig, pricing })).toMatchObject({ usd: null, peak: false });
    expect(estimateRun(10, { llmConfig, pricing, dryRun: true }))
      .toMatchObject({ usd: 0.06, peak: true });
  });

  it("uses the ranking override for a dry run rather than the global provider", () => {
    const llmConfig = config("deepseek");
    llmConfig.tasks.ranking = { primary: "openai", fallbacks: [], models: {}, thinking: null };
    expect(estimateRun(10, { llmConfig, pricing, dryRun: true }))
      .toMatchObject({ usd: null, peak: false });
  });

  it("ignores DeepSeek fallbacks and unrelated chat task providers", () => {
    const llmConfig = config("ollama");
    llmConfig.global.fallbacks = ["deepseek"];
    llmConfig.tasks.coach = { primary: "deepseek", fallbacks: [], models: {}, thinking: null };
    expect(estimateRun(10, { llmConfig, pricing })).toMatchObject({ usd: null, peak: false });
  });
});
