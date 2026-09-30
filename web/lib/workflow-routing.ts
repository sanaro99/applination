import type { LlmConfig, TaskRouting } from "./types";

export interface TaskState {
  inherit: boolean;
  primary: string;
  fallbacks: string[];
  model: string;
  models: Record<string, string>;
  thinking: "off" | "low" | "on";
  method: "llm" | "bm25";
}

export interface WorkflowState {
  primary: string;
  fallbacks: string[];
  tasks: Record<string, TaskState>;
}

export function buildWorkflowState(cfg: LlmConfig): WorkflowState {
  const globalPrimary = cfg.global.primary ?? "";
  const tasks: Record<string, TaskState> = {};
  for (const name of cfg.task_names) {
    const t = cfg.tasks[name];
    const overrides = t && (t.primary != null || t.fallbacks.length > 0 ||
      Object.keys(t.models).length > 0 || t.thinking != null);
    const primary = t?.primary ?? globalPrimary;
    tasks[name] = {
      inherit: !overrides,
      primary,
      fallbacks: overrides ? t.fallbacks : cfg.global.fallbacks,
      model: t?.models?.[primary] ?? "",
      models: { ...t?.models },
      thinking: t?.thinking === false || t?.thinking === "off" ? "off" :
        t?.thinking === "low" ? "low" : "on",
      method: name === "ranking" && t?.method === "bm25" ? "bm25" : "llm",
    };
  }
  return { primary: globalPrimary, fallbacks: cfg.global.fallbacks, tasks };
}

export function workflowConfig(state: WorkflowState) {
  const tasks: Record<string, Partial<TaskRouting>> = {};
  for (const [name, t] of Object.entries(state.tasks)) {
    if (!t.inherit) {
      const models = { ...t.models };
      if (t.model) models[t.primary] = t.model;
      else delete models[t.primary];
      tasks[name] = {
        primary: t.primary,
        fallbacks: t.fallbacks,
        models,
        thinking: t.thinking,
      };
    }
    if (name === "ranking") {
      tasks[name] = { ...tasks[name], method: t.method };
    }
  }
  return { global: { primary: state.primary, fallbacks: state.fallbacks }, tasks };
}
