import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { Run } from "@/lib/types";

/** A run is "active" while queued or running — poll fast in that window. */
export function isRunActive(status: Run["status"]): boolean {
  return status === "running" || status === "queued";
}

export function anyRunActive(runs: Run[] | undefined): boolean {
  return !!runs?.some((r) => isRunActive(r.status));
}

const FAST_MS = 4000;
const IDLE_MS = 20000;

/**
 * Single source of truth for the run list (`["runs","latest"]`). Polls fast
 * (4s) only while a run is active, and slowly (20s) when idle — so the app
 * isn't re-rendering every few seconds for nothing. Mounted once globally via
 * the watcher + status pill, which share this query key.
 */
export function useLatestRuns(): UseQueryResult<Run[]> {
  return useQuery({
    queryKey: ["runs", "latest"],
    queryFn: () => api.listRuns(),
    refetchInterval: (query) =>
      anyRunActive(query.state.data) ? FAST_MS : IDLE_MS,
  });
}
