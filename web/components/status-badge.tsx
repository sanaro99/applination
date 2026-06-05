"use client";

import type { ApplicationStatus } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const STATUS_STYLES: Record<ApplicationStatus, string> = {
  generated:
    "bg-zinc-500/15 text-zinc-700 dark:text-zinc-300 border-zinc-500/30",
  applied:
    "bg-blue-500/15 text-blue-700 dark:text-blue-300 border-blue-500/30",
  interviewing:
    "bg-violet-500/15 text-violet-700 dark:text-violet-300 border-violet-500/30",
  rejected:
    "bg-red-500/15 text-red-700 dark:text-red-300 border-red-500/30",
  offer:
    "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30",
  archived:
    "bg-zinc-500/10 text-zinc-600 dark:text-zinc-400 border-zinc-600/30",
};

const STATUS_DOTS: Record<ApplicationStatus, string> = {
  generated: "bg-zinc-500",
  applied: "bg-blue-500",
  interviewing: "bg-violet-500",
  rejected: "bg-red-500",
  offer: "bg-emerald-500",
  archived: "bg-zinc-500/60",
};

export const STATUSES: ApplicationStatus[] = [
  "generated",
  "applied",
  "interviewing",
  "rejected",
  "offer",
  "archived",
];

const STATUS_LABELS: Record<ApplicationStatus, string> = {
  generated: "Generated",
  applied: "Applied",
  interviewing: "Interviewing",
  rejected: "Rejected",
  offer: "Offer",
  archived: "Archived",
};

export function statusLabel(status: ApplicationStatus): string {
  return STATUS_LABELS[status] ?? status;
}

export function StatusBadge({ status }: { status: ApplicationStatus }) {
  return (
    <Badge variant="outline" className={cn("gap-1.5", STATUS_STYLES[status])}>
      <span className={cn("size-1.5 rounded-full", STATUS_DOTS[status])} />
      {STATUS_LABELS[status]}
    </Badge>
  );
}

export function ScoreChip({ score }: { score: number }) {
  const tone =
    score >= 80
      ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30"
      : score >= 65
        ? "bg-blue-500/15 text-blue-700 dark:text-blue-300 border-blue-500/30"
        : score >= 50
          ? "bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/30"
          : "bg-zinc-500/15 text-zinc-700 dark:text-zinc-300 border-zinc-500/30";
  return (
    <Badge variant="outline" className={cn("font-mono tabular-nums", tone)}>
      {score}
    </Badge>
  );
}
