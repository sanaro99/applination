"use client";

import { ArrowLeft, ArrowRight, Sparkles } from "lucide-react";
import type { CardComponentProps } from "nextstepjs";

import { Button, buttonVariants } from "@/components/ui/button";
import { useIsDemo } from "@/components/demo-banner";

/**
 * The tour popover. Supplied to nextstepjs as `cardComponent`, which is the
 * reason for choosing that library: the card is ours, so it inherits the app's
 * tokens and reads correctly in both themes with no vendor CSS to override.
 */
export function TourCard({
  step,
  currentStep,
  totalSteps,
  nextStep,
  prevStep,
  skipTour,
  arrow,
}: CardComponentProps) {
  const isDemo = useIsDemo();
  const isFirst = currentStep === 0;
  const isLast = currentStep === totalSteps - 1;

  return (
    <div className="w-[min(22rem,calc(100vw-2rem))] rounded-xl border border-border bg-popover p-5 text-popover-foreground shadow-2xl shadow-black/25">
      <div className="flex items-center justify-between gap-3">
        <span className="inline-flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-primary">
          <Sparkles className="size-3" />
          Step {currentStep + 1} of {totalSteps}
        </span>
        {!isLast && (
          <button
            type="button"
            onClick={skipTour}
            className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          >
            Skip tour
          </button>
        )}
      </div>

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
          <Button variant="ghost" size="sm" onClick={prevStep} className="gap-1.5">
            <ArrowLeft className="size-3.5" />
            Back
          </Button>
        )}
        <Button size="sm" onClick={nextStep} className="gap-1.5">
          {isLast ? "Done" : "Next"}
          {!isLast && <ArrowRight className="size-3.5" />}
        </Button>
      </div>

      {/* nextstepjs positions the caret; it must be rendered for it to show. */}
      {arrow}
    </div>
  );
}
