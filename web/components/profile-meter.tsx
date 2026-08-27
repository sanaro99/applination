"use client";

/**
 * How complete this profile is, part by part.
 *
 * Nine segments, and each one is a named part of the profile rather than an
 * anonymous slice of a percentage: hover or focus a segment and it tells you
 * what it is and what it is for, and on the dashboard clicking it goes to the
 * page that fills it. Those labels have always come back from
 * `GET /api/profile/strength` — a purely abstract graphic just threw them away,
 * which is what made it decorative.
 *
 * A draft story is drawn half full because it genuinely is half done, and it
 * finishes during the enrichment cascade. The counter beside the meter carries
 * the same information as the bars for anyone the graphic fails.
 */
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { motion, useReducedMotion } from "motion/react";

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { ProfilePart } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Where each part is actually filled. A segment that names itself but goes
 * nowhere is a label with extra steps, so every part has a destination.
 */
const PART_HREF: Record<string, string> = {
  contact: "/config",
  search: "/config",
  provider: "/config",
  material: "/master-data",
  resume: "/master-data",
  story_1: "/master-data",
  story_2: "/master-data",
  story_3: "/master-data",
  voice: "/master-data",
};

const FILL: Record<ProfilePart["state"], number> = {
  filled: 1,
  partial: 0.5,
  empty: 0,
};

/** Why a segment looks the way it does — a half bar does not say this alone. */
const STATE_NOTE: Record<ProfilePart["state"], string> = {
  filled: "Done",
  partial: "Draft saved",
  empty: "Not started",
};

function Segment({
  part,
  index,
  href,
  reduced,
}: {
  part: ProfilePart;
  index: number;
  href: string | null;
  reduced: boolean;
}) {
  const [justFilled, setJustFilled] = useState(false);
  const previous = useRef(part.state);

  // A part that fills while you are watching gets one brief flare. That is the
  // entire point of the enrichment cascade landing step by step; without it the
  // meter would only ever be silently longer than it was a moment ago.
  useEffect(() => {
    const changed = previous.current !== part.state;
    previous.current = part.state;
    if (!changed || part.state !== "filled" || reduced) return;
    setJustFilled(true);
    const timer = setTimeout(() => setJustFilled(false), 900);
    return () => clearTimeout(timer);
  }, [part.state, reduced]);

  const bar = (
    <span
      className={cn(
        "block h-1.5 w-full overflow-hidden rounded-full bg-muted transition-all duration-300",
        part.state === "empty" && "group-hover:bg-muted-foreground/30",
        justFilled && "ring-2 ring-primary/50",
      )}
    >
      <motion.span
        className="block h-full rounded-full bg-primary"
        initial={false}
        animate={{ width: `${FILL[part.state] * 100}%` }}
        transition={
          reduced
            ? { duration: 0 }
            : { duration: 0.45, delay: index * 0.04, ease: "easeOut" }
        }
      />
    </span>
  );

  const classes = cn(
    "group flex flex-1 items-center rounded-sm py-2 outline-none",
    "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
    // Not decorative even where it does not link: it still explains itself.
    href ? "cursor-pointer" : "cursor-help",
  );
  const described = `${part.label} — ${STATE_NOTE[part.state]}. ${part.hint}`;

  return (
    <Tooltip>
      {href ? (
        <TooltipTrigger
          render={<Link href={href} />}
          aria-label={described}
          className={classes}
        >
          {bar}
        </TooltipTrigger>
      ) : (
        <TooltipTrigger aria-label={described} className={classes}>
          {bar}
        </TooltipTrigger>
      )}
      <TooltipContent side="bottom" className="flex-col items-start gap-1 py-2">
        <span className="font-medium">{part.label}</span>
        <span className="opacity-80">{part.hint}</span>
        <span className="opacity-60">{STATE_NOTE[part.state]}</span>
      </TooltipContent>
    </Tooltip>
  );
}

export function ProfileMeter({
  parts,
  filled,
  total,
  caption,
  interactive = false,
  className,
}: {
  parts: ProfilePart[];
  filled: number;
  total: number;
  /** Names the meter wherever it appears without a card title above it. */
  caption?: string;
  /** Dashboard only: a segment links to the page that fills it. On the journey
   *  a click would eject you mid-chapter, so there it only names itself. */
  interactive?: boolean;
  className?: string;
}) {
  const reduced = useReducedMotion() ?? false;

  return (
    <div className={cn("w-full", className)}>
      <div className="flex items-baseline justify-between gap-3">
        {caption ? (
          <span className="text-xs font-medium">{caption}</span>
        ) : (
          <span aria-hidden />
        )}
        <span className="text-xs tabular-nums text-muted-foreground">
          {filled} of {total}
        </span>
      </div>

      {parts.length ? (
        <div className="flex items-center gap-1">
          {parts.map((part, index) => (
            <Segment
              key={part.id}
              part={part}
              index={index}
              reduced={reduced}
              href={interactive ? (PART_HREF[part.id] ?? null) : null}
            />
          ))}
        </div>
      ) : (
        // Still loading. Hold the row's height so nothing jumps in under the
        // user once the real states arrive.
        <div className="flex items-center gap-1" aria-hidden>
          {Array.from({ length: total }).map((_, index) => (
            <span key={index} className="flex flex-1 items-center py-2">
              <span className="block h-1.5 w-full rounded-full bg-muted" />
            </span>
          ))}
        </div>
      )}

      <p className="sr-only" aria-live="polite">
        {filled} of {total} parts of your profile are complete.
      </p>
    </div>
  );
}
