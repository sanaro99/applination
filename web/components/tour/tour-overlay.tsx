"use client";

import { useLayoutEffect, useRef, useState } from "react";

import { TourCard } from "@/components/tour/tour-card";
import type { TourStep } from "@/components/tour/tour-steps";
import {
  SPOTLIGHT_PADDING,
  computeCardPosition,
  type Rect,
} from "@/components/tour/tour-position";

/** Indigo-tinted scrim, matching the app's accent. */
const DIM = "rgba(49, 46, 129, 0.65)";
const Z_DIM = 998;
const Z_CARD = 1000;

/** Matches the sidebar's own collapse point in app-shell.tsx. */
const NARROW_VIEWPORT_QUERY = "(max-width: 767px)";

interface TourOverlayProps {
  step: TourStep;
  stepNumber: number;
  totalSteps: number;
  /** Bounding rect of the spotlighted element, or null to center the card. */
  targetRect: Rect | null;
  /** False while still searching for the step's element — dims the page
   * without popping the card in at a position that's about to change. */
  showCard: boolean;
  onNext: () => void;
  onPrev: () => void;
  onSkip: () => void;
}

/** Dims the page around `target` with four bands, leaving it uncovered and
 * interactive, and draws a glowing ring around it. */
function Spotlight({ target }: { target: Rect }) {
  const top = target.top - SPOTLIGHT_PADDING;
  const left = target.left - SPOTLIGHT_PADDING;
  const width = target.width + SPOTLIGHT_PADDING * 2;
  const height = target.height + SPOTLIGHT_PADDING * 2;
  const bandStyle = {
    position: "fixed" as const,
    background: DIM,
    zIndex: Z_DIM,
    pointerEvents: "auto" as const,
  };
  return (
    <>
      <div
        aria-hidden
        style={{ ...bandStyle, top: 0, left: 0, right: 0, height: Math.max(top, 0) }}
      />
      <div
        aria-hidden
        style={{
          ...bandStyle,
          top: top + height,
          left: 0,
          right: 0,
          bottom: 0,
        }}
      />
      <div
        aria-hidden
        style={{ ...bandStyle, top, left: 0, width: Math.max(left, 0), height }}
      />
      <div
        aria-hidden
        style={{ ...bandStyle, top, left: left + width, right: 0, height }}
      />
      <div
        aria-hidden
        className="rounded-2xl ring-2 ring-primary/80 transition-[top,left,width,height] duration-200 ease-out"
        style={{
          position: "fixed",
          top,
          left,
          width,
          height,
          zIndex: Z_DIM,
          pointerEvents: "none",
          boxShadow: "0 0 24px 2px color-mix(in oklch, var(--primary) 55%, transparent)",
        }}
      />
    </>
  );
}

function useIsNarrowViewport(): boolean {
  const [narrow, setNarrow] = useState(false);
  useLayoutEffect(() => {
    const mq = window.matchMedia(NARROW_VIEWPORT_QUERY);
    const update = () => setNarrow(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return narrow;
}

export function TourOverlay({
  step,
  stepNumber,
  totalSteps,
  targetRect,
  showCard,
  onNext,
  onPrev,
  onSkip,
}: TourOverlayProps) {
  const isNarrow = useIsNarrowViewport();
  const cardRef = useRef<HTMLDivElement>(null);
  const [cardSize, setCardSize] = useState<{ width: number; height: number } | null>(
    null,
  );
  const centered = !targetRect || isNarrow;

  // Height depends on copy length, so it's measured rather than assumed.
  useLayoutEffect(() => {
    const el = cardRef.current;
    if (!el || centered) return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setCardSize((prev) =>
        prev && prev.width === width && prev.height === height
          ? prev
          : { width, height },
      );
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [centered]);

  const canPlace = !centered && targetRect && cardSize;
  const placement =
    canPlace && targetRect
      ? computeCardPosition(
          targetRect,
          step.side ?? "bottom",
          cardSize!.width,
          cardSize!.height,
          window.innerWidth,
          window.innerHeight,
        )
      : null;
  const visible = showCard && (centered || !!placement);

  return (
    <>
      {targetRect && !isNarrow ? (
        <Spotlight target={targetRect} />
      ) : (
        <div
          aria-hidden
          className="fixed inset-0"
          style={{ background: DIM, zIndex: Z_DIM, pointerEvents: "auto" }}
        />
      )}

      <div
        ref={cardRef}
        style={{
          position: "fixed",
          zIndex: Z_CARD,
          pointerEvents: "auto",
          transition: placement ? "top 0.2s ease, left 0.2s ease" : undefined,
          visibility: visible ? "visible" : "hidden",
          ...(centered
            ? { top: "50%", left: "50%", transform: "translate(-50%, -50%)" }
            : placement
              ? { top: placement.top, left: placement.left }
              : { top: -9999, left: -9999 }),
        }}
      >
        <TourCard
          step={step}
          stepNumber={stepNumber}
          totalSteps={totalSteps}
          onNext={onNext}
          onPrev={onPrev}
          onSkip={onSkip}
        />
      </div>
    </>
  );
}
