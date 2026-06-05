"use client";

import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

export interface LogLine {
  level: string;
  msg: string;
  ts: number;
}

export function LogTerminal({
  lines,
  className,
  emptyText = "Waiting for logs…",
}: {
  lines: LogLine[];
  className?: string;
  emptyText?: string;
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines.length]);

  return (
    <div
      className={cn(
        "overflow-hidden rounded-xl border border-border bg-zinc-950 text-zinc-200",
        className,
      )}
    >
      <div className="flex items-center gap-1.5 border-b border-border/60 px-3 py-2">
        <div className="size-2 rounded-full bg-red-500/80" />
        <div className="size-2 rounded-full bg-yellow-500/80" />
        <div className="size-2 rounded-full bg-green-500/80" />
        <span className="ml-2 text-xs font-medium text-zinc-400">
          pipeline.log
        </span>
      </div>
      <div
        ref={scrollRef}
        className="h-72 overflow-auto p-3 font-mono text-xs leading-relaxed"
      >
        {lines.length === 0 ? (
          <div className="text-zinc-500">{emptyText}</div>
        ) : (
          lines.map((l, i) => (
            <div
              key={i}
              className={cn(
                "whitespace-pre-wrap break-words",
                l.level === "WARNING" && "text-yellow-300",
                l.level === "ERROR" && "text-red-400",
                l.level === "INFO" && "text-zinc-200",
                l.level === "DEBUG" && "text-zinc-500",
              )}
            >
              {l.msg}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
