"use client";

import { useEffect, useRef } from "react";
import { toast } from "sonner";

import { useLatestRuns } from "@/lib/use-latest-runs";

/**
 * Mounted once in the app shell. Watches the run list and fires a toast when a
 * run transitions to done/error, so background runs surface even if the user
 * navigated away from the live run page.
 */
export function RunActivityWatcher() {
  const { data } = useLatestRuns();
  const seen = useRef<Map<number, string>>(new Map());
  const initialized = useRef(false);

  useEffect(() => {
    if (!data) return;
    // First load: record current statuses without toasting (don't replay
    // already-finished runs).
    if (!initialized.current) {
      data.forEach((r) => seen.current.set(r.id, r.status));
      initialized.current = true;
      return;
    }
    for (const r of data) {
      const prev = seen.current.get(r.id);
      if (prev && prev !== r.status) {
        if (r.status === "done") {
          toast.success(
            `Run #${r.id} finished — ${r.applications_created} application(s)`,
          );
        } else if (r.status === "cancelled") {
          toast.message(
            `Run #${r.id} stopped — ${r.applications_created} application(s) completed`,
          );
        } else if (r.status === "error") {
          toast.error(`Run #${r.id} failed${r.error ? `: ${r.error}` : ""}`);
        }
      }
      seen.current.set(r.id, r.status);
    }
  }, [data]);

  return null;
}
