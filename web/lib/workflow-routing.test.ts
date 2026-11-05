import { describe, expect, it } from "vitest";
import { buildWorkflowState, workflowConfig } from "./workflow-routing";
import type { LlmConfig } from "./types";

const base: LlmConfig = {
  task_names: ["ranking", "tailoring"],
  global: { primary: "demo", fallbacks: [] },
  providers: [],
  tasks: {},
};

describe("ranking workflow settings", () => {
  it("keeps local ranking when provider routing inherits the global default", () => {
    const state = buildWorkflowState({ ...base, tasks: {
      ranking: { method: "bm25", primary: null, fallbacks: [], models: {}, thinking: null },
    } });
    expect(state.tasks.ranking.inherit).toBe(true);
    expect(workflowConfig(state).tasks.ranking).toEqual({ method: "bm25" });
  });

  it("can switch local ranking back to the inherited LLM", () => {
    const state = buildWorkflowState(base);
    state.tasks.ranking.method = "llm";
    expect(workflowConfig(state).tasks.ranking).toEqual({ method: "llm" });
  });

  it("preserves provider overrides while switching ranking methods", () => {
    const state = buildWorkflowState({ ...base, tasks: {
      ranking: { method: "llm", primary: "groq", fallbacks: ["gemini"],
        models: { groq: "test-model", gemini: "fallback-model" }, thinking: "off" },
    } });
    state.tasks.ranking.method = "bm25";
    expect(workflowConfig(state).tasks.ranking).toEqual({ method: "bm25", primary: "groq",
      fallbacks: ["gemini"], models: { groq: "test-model", gemini: "fallback-model" }, thinking: "off" });
    expect(workflowConfig(state).tasks.tailoring).toBeUndefined();
  });
});
