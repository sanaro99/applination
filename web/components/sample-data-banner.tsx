"use client";

/**
 * "There is still sample data in here."
 *
 * Dismissible for the session, never permanently, and driven by server state so
 * it survives a reload and follows the account to another browser. Sample values
 * quietly becoming someone's real cover letter is the single most likely way the
 * "use a sample" affordance turns into a bug report.
 *
 * Deliberately no wipe button: deleting a user's master data from a banner click
 * is irreversible and needs a real confirmation flow, which is its own piece of
 * work. The banner points at the two pages where the values actually live.
 */
import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { TriangleAlert, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

export function SampleDataBanner() {
  const qc = useQueryClient();
  const [dismissed, setDismissed] = useState(false);

  const { data } = useQuery({
    queryKey: ["onboarding-status"],
    queryFn: () => api.onboardingStatus(),
    retry: false,
  });

  const clear = useMutation({
    mutationFn: () => api.clearSampleUsed(),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["onboarding-status"] }),
  });

  if (!data?.sample_data || dismissed) return null;

  return (
    <div className="flex flex-wrap items-start gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-sm">
      <TriangleAlert className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" />
      <div className="flex-1 space-y-2">
        <p>
          Sample values are still in your profile — replace them before you run,
          or your documents will be about somebody fictional.
        </p>
        <div className="flex flex-wrap gap-2">
          <Link
            href="/master-data"
            className="font-medium underline underline-offset-4"
          >
            Master data
          </Link>
          <Link
            href="/config"
            className="font-medium underline underline-offset-4"
          >
            Config
          </Link>
          <button
            onClick={() => clear.mutate()}
            className="font-medium underline underline-offset-4"
          >
            I&apos;ve replaced them
          </button>
        </div>
      </div>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label="Hide for now"
        onClick={() => setDismissed(true)}
      >
        <X className="size-4" />
      </Button>
    </div>
  );
}
