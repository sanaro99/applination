"use client";

/**
 * One section of the resume, collapsed by default.
 *
 * The `why` line is where the template's YAML comments went. They existed to
 * explain the file to somebody reading raw YAML; the form is a better home for
 * the same information, and it reaches the people who need it most.
 */
import { useState, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";

export function SectionCard({
  title,
  why,
  summary,
  defaultOpen = false,
  children,
}: {
  title: string;
  why: string;
  summary: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="rounded-xl border border-border">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 rounded-xl px-4 py-3 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ChevronRight
          className={cn(
            "size-4 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-90",
          )}
        />
        <span className="flex-1">
          <span className="block font-medium">{title}</span>
          <span className="block text-xs text-muted-foreground">{why}</span>
        </span>
        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
          {summary}
        </span>
      </button>
      {open ? <div className="space-y-3 border-t border-border p-4">{children}</div> : null}
    </div>
  );
}
