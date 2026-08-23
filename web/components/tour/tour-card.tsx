"use client";

import { ArrowLeft, ArrowRight, Sparkles } from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import { useIsDemo } from "@/components/demo-banner";
import type { TourStep } from "@/components/tour/tour-steps";

interface TourCardProps {
  step: TourStep;
  stepNumber: number;
  totalSteps: number;
  onNext: () => void;
  onPrev: () => void;
  onSkip: () => void;
}

/**
 * The tour popover content. Positioned by `TourOverlay`, which passes down a
 * fixed-position wrapper — this component only renders what's inside it, so
 * it stays a plain function of its props and is easy to reason about
 * independent of the positioning math.
 */
export function TourCard({
  step,
  stepNumber,
  totalSteps,
  onNext,
  onPrev,
  onSkip,
}: TourCardProps) {
  const isDemo = useIsDemo();
  const isFirst = stepNumber === 1;
  const isLast = stepNumber === totalSteps;

  return (
    <div className="w-[min(22rem,calc(100vw-2rem))] rounded-xl border border-border bg-popover p-5 text-popover-foreground shadow-2xl shadow-black/25">
      <div className="flex items-center justify-between gap-3">
        <span className="inline-flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-primary">
          <Sparkles className="size-3" />
          Step {stepNumber} of {totalSteps}
        </span>
        {!isLast && (
          <button
            type="button"
            onClick={onSkip}
            className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          >
            Skip tour
          </button>
        )}
      </div>

      {step.navHint && (
        <p className="mt-2.5 text-xs font-medium text-muted-foreground">
          You got here via <span className="text-foreground">{step.navHint}</span>
        </p>
      )}

      <h2 className="mt-3 font-heading text-base font-semibold tracking-tight">
        {step.title}
      </h2>
      <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
        {step.content}
      </p>

      {isLast && isDemo && (
        <a
          href="/signup"
          className={buttonVariants({ size: "sm", className: "mt-4 w-full" })}
        >
          Create your own account
        </a>
      )}

      <div className="mt-4 flex items-center justify-between gap-2">
        {/* Placeholder keeps "Next" hard right when there is nothing to go back to. */}
        {isFirst ? (
          <span />
        ) : (
          <Button variant="ghost" size="sm" onClick={onPrev} className="gap-1.5">
            <ArrowLeft className="size-3.5" />
            Back
          </Button>
        )}
        <Button size="sm" onClick={onNext} className="gap-1.5">
          {isLast ? "Done" : "Next"}
          {!isLast && <ArrowRight className="size-3.5" />}
        </Button>
      </div>
    </div>
  );
}
