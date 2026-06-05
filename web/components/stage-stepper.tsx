"use client";

import { CheckCircle2, Loader2, Circle } from "lucide-react";
import { BorderBeam } from "@/components/ui/border-beam";
import { cn } from "@/lib/utils";

export type StageId = "fetch" | "rank" | "tailor" | "tracker";
export type StageState = "pending" | "active" | "done" | "error";

const STAGES: { id: StageId; label: string }[] = [
  { id: "fetch", label: "Fetch" },
  { id: "rank", label: "Rank" },
  { id: "tailor", label: "Tailor" },
  { id: "tracker", label: "Tracker" },
];

export function StageStepper({
  stageStates,
}: {
  stageStates: Record<StageId, StageState>;
}) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {STAGES.map((s) => {
        const state = stageStates[s.id];
        return (
          <div
            key={s.id}
            className={cn(
              "relative overflow-hidden rounded-xl border p-4 transition-colors",
              state === "active" && "border-primary/50 bg-primary/5",
              state === "done" && "border-emerald-500/40 bg-emerald-500/5",
              state === "error" && "border-destructive/50 bg-destructive/5",
              state === "pending" && "border-border bg-card",
            )}
          >
            {state === "active" && (
              <BorderBeam
                size={120}
                duration={6}
                colorFrom="var(--color-chart-1)"
                colorTo="var(--color-chart-2)"
              />
            )}
            <div className="flex items-center gap-3">
              {state === "done" ? (
                <CheckCircle2 className="size-5 text-emerald-500" />
              ) : state === "active" ? (
                <Loader2 className="size-5 animate-spin text-primary" />
              ) : (
                <Circle className="size-5 text-muted-foreground" />
              )}
              <div>
                <div className="text-sm font-medium">{s.label}</div>
                <div className="text-xs uppercase tracking-wide text-muted-foreground">
                  {state}
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
