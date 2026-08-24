"use client";

/**
 * The fingerprint: a profile that is unique, owned, and not transferable.
 *
 * Not a progress bar in costume — the ridges map 1:1 to real profile state from
 * GET /api/profile/strength, and the thing genuinely completes. A draft story
 * shows as a half-filled ridge and finishes during the enrichment cascade,
 * which is what makes that moment read as a reward rather than a wait.
 *
 * The drawing is never the only signal: the counter below it and its aria-live
 * region carry the same information for anyone the metaphor fails.
 */
import { motion, useReducedMotion } from "motion/react";

import { RIDGE_ORDER, fillFraction, ridgePath } from "@/lib/ridge-geometry";
import type { Ridge } from "@/lib/api";
import { cn } from "@/lib/utils";

export function Fingerprint({
  ridges,
  filled,
  total,
  className,
  size = 120,
  showCounter = true,
}: {
  ridges: Ridge[];
  filled: number;
  total: number;
  className?: string;
  size?: number;
  showCounter?: boolean;
}) {
  const reduced = useReducedMotion();
  const byId = new Map(ridges.map((r) => [r.id, r]));

  return (
    <div className={cn("flex flex-col items-center gap-2", className)}>
      <svg
        width={size}
        height={size}
        viewBox="0 0 120 120"
        role="img"
        aria-label={`Profile fingerprint, ${filled} of ${total} parts complete`}
      >
        {RIDGE_ORDER.map((id, i) => {
          const state = byId.get(id)?.state ?? "empty";
          const fraction = fillFraction(state);
          return (
            <g key={id}>
              <path
                d={ridgePath(i)}
                fill="none"
                stroke="currentColor"
                strokeWidth={1.5}
                strokeLinecap="round"
                className="text-muted-foreground/20"
              />
              <motion.path
                d={ridgePath(i)}
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                strokeLinecap="round"
                className="text-primary"
                initial={false}
                animate={{ pathLength: fraction }}
                transition={
                  reduced
                    ? { duration: 0 }
                    : { duration: 0.7, delay: i * 0.05, ease: "easeOut" }
                }
              />
            </g>
          );
        })}
      </svg>
      {showCounter ? (
        <p className="text-xs text-muted-foreground" aria-live="polite">
          {filled} of {total} filled
        </p>
      ) : null}
    </div>
  );
}
