"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ExternalLink, Loader2, Sparkles, X, Undo2 } from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ScoreChip } from "@/components/status-badge";
import { api } from "@/lib/api";

type Filter = "all" | "selected" | "rejected" | "dismissed";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "selected", label: "Auto-selected" },
  { key: "rejected", label: "Not selected" },
  { key: "dismissed", label: "Dismissed" },
];

export function RankedPool({
  runId,
  active = false,
}: {
  runId: number;
  active?: boolean;
}) {
  const router = useRouter();
  const qc = useQueryClient();
  const [filter, setFilter] = useState<Filter>("all");

  const { data, isLoading } = useQuery({
    queryKey: ["ranked", runId, filter],
    queryFn: () => api.listRankedJobs(runId, filter),
    // The ranked pool only grows while the run is actively ranking; once it's
    // done there's nothing new to fetch.
    refetchInterval: active ? 5000 : false,
  });

  const generate = useMutation({
    mutationFn: (rankedId: number) => api.generateRanked(rankedId),
    onSuccess: (r) => {
      toast.success("Generating — opening the run…");
      qc.invalidateQueries({ queryKey: ["ranked", runId] });
      router.push(`/runs/${r.run_id}`);
    },
    onError: (e) => toast.error(String(e)),
  });

  const dismiss = useMutation({
    mutationFn: ({ id, dismissed }: { id: number; dismissed: boolean }) =>
      api.dismissRanked(id, dismissed),
    onSuccess: (r) => {
      toast.success(
        r.dismissed
          ? "Dismissed — hidden from future runs"
          : "Restored",
      );
      qc.invalidateQueries({ queryKey: ["ranked", runId] });
    },
    onError: (e) => toast.error(String(e)),
  });

  if (isLoading) return <Skeleton className="h-64 w-full" />;

  const rows = data ?? [];

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1">
        {FILTERS.map((f) => (
          <Button
            key={f.key}
            variant={filter === f.key ? "secondary" : "ghost"}
            size="sm"
            onClick={() => setFilter(f.key)}
          >
            {f.label}
          </Button>
        ))}
      </div>

      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No ranked jobs recorded for this run. (Runs started before this
          feature, or runs with no jobs above threshold, have none.)
        </p>
      ) : (
        <ul className="space-y-2">
          {rows.map((r) => (
            <li
              key={r.id}
              className={`flex items-start justify-between gap-3 rounded-md border border-border/60 p-3 ${
                r.dismissed ? "opacity-50" : ""
              }`}
            >
              <div className="min-w-0 space-y-1">
                <div className="flex items-center gap-2">
                  <ScoreChip score={r.match_score} />
                  <span className="truncate font-medium">{r.company}</span>
                  {r.selected && (
                    <Badge variant="outline" className="text-xs">
                      auto-selected
                    </Badge>
                  )}
                  {r.dismissed && (
                    <Badge variant="secondary" className="text-xs">
                      dismissed
                    </Badge>
                  )}
                </div>
                <div className="text-sm text-muted-foreground">{r.title}</div>
                {r.match_reason && (
                  <p className="text-xs text-muted-foreground">
                    <span className="font-medium text-foreground/70">
                      Why this score:{" "}
                    </span>
                    {r.match_reason}
                  </p>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-1">
                {r.url && (
                  <a
                    href={r.url}
                    target="_blank"
                    rel="noreferrer"
                    className={buttonVariants({ variant: "ghost", size: "icon" })}
                    aria-label="Open job posting"
                  >
                    <ExternalLink className="size-4" />
                  </a>
                )}
                {r.application_id != null ? (
                  <Link
                    href={`/applications/${r.application_id}`}
                    className={buttonVariants({ variant: "outline", size: "sm" })}
                  >
                    View
                  </Link>
                ) : r.dismissed ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => dismiss.mutate({ id: r.id, dismissed: false })}
                    disabled={dismiss.isPending && dismiss.variables?.id === r.id}
                  >
                    <Undo2 className="size-3.5" />
                    Restore
                  </Button>
                ) : (
                  <>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => generate.mutate(r.id)}
                      disabled={
                        generate.isPending && generate.variables === r.id
                      }
                    >
                      {generate.isPending && generate.variables === r.id ? (
                        <Loader2 className="size-3.5 animate-spin" />
                      ) : (
                        <Sparkles className="size-3.5" />
                      )}
                      Generate
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      aria-label="Dismiss — hide from future runs"
                      title="Not interested — hide from future runs"
                      onClick={() => dismiss.mutate({ id: r.id, dismissed: true })}
                      disabled={dismiss.isPending && dismiss.variables?.id === r.id}
                    >
                      <X className="size-4" />
                    </Button>
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
