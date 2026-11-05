import { QueryClient, QueryObserver } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";

import { currentRunLlmConfig, runLlmConfigQuery } from "./run-llm-config";
import type { LlmConfig } from "./types";

const cached: LlmConfig = {
  global: { primary: "deepseek", fallbacks: [] }, tasks: {}, task_names: [], providers: [],
};

afterEach(() => vi.unstubAllGlobals());

it("refreshes routing after returning from Settings even when cached routing is fresh", async () => {
  const client = new QueryClient({ defaultOptions: { queries: {
    staleTime: 30_000, refetchOnMount: false, refetchOnWindowFocus: false, retry: false,
  } } });
  client.setQueryData(["llm-config"], cached);
  const updated = { ...cached, global: { primary: "ollama", fallbacks: [] } };
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify(updated)));
  const observer = new QueryObserver(client, runLlmConfigQuery);
  const unsubscribe = observer.subscribe(() => {});
  try {
    // A cached DeepSeek result must not be used while checking for changed routing.
    expect(currentRunLlmConfig(observer.getCurrentResult())).toBeUndefined();
    await vi.waitFor(() => expect(observer.getCurrentResult().data).toEqual(updated));
    expect(currentRunLlmConfig(observer.getCurrentResult())?.global.primary).toBe("ollama");
  } finally {
    unsubscribe();
    client.clear();
  }
});

it("does not resurrect cached DeepSeek pricing when the refresh fails", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(["llm-config"], cached);
  vi.stubGlobal("fetch", async () => new Response('{"detail":"unavailable"}', { status: 503 }));
  const observer = new QueryObserver(client, runLlmConfigQuery);
  const unsubscribe = observer.subscribe(() => {});
  try {
    await vi.waitFor(() => expect(observer.getCurrentResult().isError).toBe(true));
    expect(observer.getCurrentResult().data).toEqual(cached);
    expect(currentRunLlmConfig(observer.getCurrentResult())).toBeUndefined();
  } finally {
    unsubscribe();
    client.clear();
  }
});
