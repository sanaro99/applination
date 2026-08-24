"use client";

/**
 * Chapter 5 — the payoff.
 *
 * This is the moment a first-time user believes the product exists: real
 * postings, real companies, at zero token cost, because fetch_all is pure HTTP.
 *
 * It must never block. A scrape that times out, errors or only half the boards
 * answer still lets the user walk on — and says which of those happened rather
 * than showing a confident number it does not have.
 */
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";

import { NumberTicker } from "@/components/ui/number-ticker";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";

import { JourneyShell } from "../journey-shell";

export function ChapterPayoff({
  onNext,
  onBack,
}: {
  onNext: () => void;
  onBack: () => void;
}) {
  const { data } = useQuery({
    queryKey: ["job-preview"],
    queryFn: () => api.jobPreview(),
    refetchInterval: (query) =>
      query.state.data?.state === "running" ? 2000 : false,
    retry: false,
  });

  // Chapter 4 normally starts this, but the user can reach here by going back
  // and forward, or by reloading, and an idle preview would just sit there.
  useEffect(() => {
    if (data?.state === "idle") void api.startJobPreview().catch(() => {});
  }, [data?.state]);

  const running = !data || data.state === "running" || data.state === "idle";
  const partial =
    data?.state === "ready" &&
    data.sources_total > 0 &&
    data.sources_ok < data.sources_total;

  return (
    <JourneyShell
      eyebrow="Chapter 5"
      heading={
        running
          ? "Having a look at what's out there…"
          : data?.state === "error"
            ? "That didn't work, and it isn't your fault."
            : "Here's what's live right now."
      }
      onBack={onBack}
      onNext={onNext}
      nextLabel="Continue"
    >
      {running ? (
        <div className="space-y-3">
          <Skeleton className="h-10 w-48" />
          <Skeleton className="h-4 w-72" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : data?.state === "error" ? (
        <p className="text-base text-muted-foreground">
          I couldn&apos;t reach the job boards just now — that&apos;s on me, not
          you. It&apos;ll work later.
        </p>
      ) : (
        <div className="space-y-4">
          <div className="font-heading text-5xl font-extrabold tabular-nums">
            <NumberTicker value={data?.total ?? 0} />
          </div>
          <p className="text-base text-muted-foreground">
            {data?.total ?? 0} live roles right now, across{" "}
            {data?.sources_total ?? 0} boards. {data?.matched ?? 0} look like
            you.
            {partial
              ? ` (across ${data?.sources_ok} of ${data?.sources_total} — a couple didn't answer)`
              : ""}
          </p>

          {data?.sample.length ? (
            <ul className="max-h-72 space-y-1 overflow-y-auto rounded-lg border border-border p-2">
              {data.sample.map((job) => (
                <li key={`${job.company}-${job.title}-${job.url}`}>
                  <a
                    href={job.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center justify-between gap-3 rounded-md px-3 py-2 text-sm transition-colors hover:bg-muted/40"
                  >
                    <span className="flex min-w-0 flex-col">
                      <span className="truncate font-medium">{job.title}</span>
                      <span className="truncate text-xs text-muted-foreground">
                        {job.company}
                        {job.location ? ` · ${job.location}` : ""}
                      </span>
                    </span>
                    <ExternalLink className="size-3.5 shrink-0 text-muted-foreground" />
                  </a>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      )}
    </JourneyShell>
  );
}
