/**
 * Rough per-run cost + time estimate for the confirmation dialog.
 *
 * Constants are order-of-magnitude, derived from the cost analysis at current
 * DeepSeek V4-Flash flat pricing ($0.14/$0.28 per M tokens):
 *   - ranking cost is ~fixed per run (scales with jobs *fetched*, not the count)
 *   - tailoring + cover letters scale ~linearly with the selected count
 * Actuals swing with retries/cache hits, so this is labelled "rough" in the UI.
 */
export interface RunEstimate {
  usd: number;
  minutes: number;
}

const RANKING_USD = 0.03; // fixed per run (all fetched jobs ranked)
const PER_JOB_USD = 0.005; // tailor + cover letter per selected job
const BASE_SEC = 75; // fetch + rank
const PER_JOB_SEC = 30; // tailor + cover per selected job

export function estimateRun(
  count: number,
  opts?: { dryRun?: boolean; peak?: boolean },
): RunEstimate {
  const dry = opts?.dryRun ?? false;
  const peakMult = opts?.peak ? 2 : 1;
  const usd = dry
    ? RANKING_USD * peakMult
    : (RANKING_USD + PER_JOB_USD * count) * peakMult;
  const minutes = (BASE_SEC + (dry ? 0 : PER_JOB_SEC * count)) / 60;
  return { usd, minutes };
}

export function formatUsd(n: number): string {
  return n < 0.01 ? "<$0.01" : `$${n.toFixed(2)}`;
}

export function formatMinutes(m: number): string {
  if (m < 1) return "<1 min";
  const rounded = Math.round(m);
  return `~${rounded} min`;
}

export function formatElapsed(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return rem ? `${m}m ${rem}s` : `${m}m`;
}
