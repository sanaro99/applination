import { api } from "./api";
import type { LlmConfig } from "./types";

export const runLlmConfigQuery = {
  queryKey: ["llm-config"],
  queryFn: () => api.getLlmConfig(),
  refetchOnMount: "always" as const,
};

export function currentRunLlmConfig(result: {
  data?: LlmConfig;
  isFetching: boolean;
  isError: boolean;
}): LlmConfig | undefined {
  return result.isFetching || result.isError ? undefined : result.data;
}
