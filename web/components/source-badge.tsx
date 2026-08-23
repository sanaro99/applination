"use client";

import { Badge } from "@/components/ui/badge";

const SOURCE_DISPLAY_NAMES: Record<string, string> = {
  remotive: "Remotive",
  themuse: "The Muse",
  adzuna: "Adzuna",
  jsearch: "JSearch",
  greenhouse: "Greenhouse",
  simplify_github: "SimplifyJobs",
  lever: "Lever",
};

/** Base source id, stripped of any `:company`/`:country` qualifier. */
function sourceBase(source: string): string {
  return source.split(":", 1)[0];
}

export function sourceLabel(source: string): string {
  const base = sourceBase(source);
  return SOURCE_DISPLAY_NAMES[base] ?? base;
}

export function SourceBadge({ source }: { source: string }) {
  if (!source) return null;
  const qualified = source.includes(":");
  return (
    <Badge
      variant="outline"
      className="text-muted-foreground"
      title={qualified ? source : undefined}
    >
      {sourceLabel(source)}
    </Badge>
  );
}
