"use client";

/**
 * What this save will actually do.
 *
 * The old signal was the words "unsaved changes", which asked the user to
 * approve something they could not see — worst of all right after an AI rewrite,
 * where the whole document may have moved. Both editors feed the same
 * `DiffLine[]`, so an AI rewrite and a hand edit are reported identically.
 */
import { useState } from "react";
import { ChevronDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import { diffLines, type DiffLine } from "@/lib/resume-diff";
import { cn } from "@/lib/utils";

export function ChangeReview({
  before,
  after,
  className,
}: {
  before: string[];
  after: string[];
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const diff = diffLines(before, after);
  const added = diff.filter((l) => l.type === "add").length;
  const removed = diff.filter((l) => l.type === "remove").length;

  if (!added && !removed) return null;

  const summary = [
    added ? `${added} added` : null,
    removed ? `${removed} removed` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className={cn("space-y-2", className)}>
      <Button
        size="sm"
        variant="ghost"
        className="h-7 gap-1.5 px-2 text-xs"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <ChevronDown
          className={cn("size-3.5 transition-transform", open && "rotate-180")}
        />
        {open ? "Hide changes" : "Review changes"}
        <span className="text-muted-foreground">· {summary}</span>
      </Button>

      {open ? (
        <div className="max-h-72 overflow-auto rounded-lg border border-border bg-muted/30 p-2 font-mono text-xs leading-relaxed">
          {diff.map((line, i) => (
            <DiffRow key={i} line={line} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function DiffRow({ line }: { line: DiffLine }) {
  if (line.type === "same") {
    return (
      <div className="text-muted-foreground/60">
        <span className="select-none pr-2"> </span>
        {line.text}
      </div>
    );
  }
  const add = line.type === "add";
  return (
    <div
      className={cn(
        "rounded-sm px-1",
        add
          ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
          : "bg-rose-500/10 text-rose-600 dark:text-rose-400",
      )}
    >
      <span className="select-none pr-2">{add ? "+" : "−"}</span>
      {line.text}
    </div>
  );
}
