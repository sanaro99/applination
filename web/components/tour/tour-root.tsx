"use client";

import { useQuery } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { api } from "@/lib/api";
import { TourOverlay } from "@/components/tour/tour-overlay";
import { TOUR_START_PATH, buildTour, type TourStep } from "@/components/tour/tour-steps";
import type { Rect } from "@/components/tour/tour-position";

const SEEN_PREFIX = "applination.tour.v1.seen.";
/** Gives up waiting for a step's element after roughly this long. */
const SEARCH_TIMEOUT_MS = 2000;

function rectsEqual(a: Rect, b: DOMRect): boolean {
  return a.top === b.top && a.left === b.left && a.width === b.width && a.height === b.height;
}

function toRect(r: DOMRect): Rect {
  return { top: r.top, left: r.left, right: r.right, bottom: r.bottom, width: r.width, height: r.height };
}

/**
 * Finds `selector` in the DOM (retrying while it mounts, e.g. behind a data
 * fetch or a route transition), scrolls it into view once, then tracks its
 * rect on every frame — one loop covers scroll, resize and layout shifts
 * without wiring up separate listeners for each.
 */
function useTargetRect(selector: string | undefined, scrollOffset: number | undefined) {
  const [rect, setRect] = useState<Rect | null>(null);
  const [searching, setSearching] = useState(!!selector);

  useEffect(() => {
    let raf = 0;
    let cancelled = false;
    let found = false;
    const deadline = Date.now() + SEARCH_TIMEOUT_MS;

    const measure = () => {
      if (cancelled) return;
      if (!selector) {
        setRect(null);
        setSearching(false);
        return;
      }
      const el = document.querySelector(selector);
      if (!el) {
        setRect(null);
        setSearching(Date.now() < deadline);
        raf = requestAnimationFrame(measure);
        return;
      }
      if (!found) {
        found = true;
        (el as HTMLElement).style.scrollMarginTop = `${scrollOffset ?? 0}px`;
        el.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
      setSearching(false);
      const r = el.getBoundingClientRect();
      setRect((prev) => (prev && rectsEqual(prev, r) ? prev : toRect(r)));
      raf = requestAnimationFrame(measure);
    };

    raf = requestAnimationFrame(measure);
    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
    };
  }, [selector, scrollOffset]);

  return { rect, searching };
}

interface TourState {
  active: boolean;
  start: () => void;
  skip: () => void;
}

const TourStateContext = createContext<TourState | null>(null);

/** Per-user so switching accounts on one browser does not inherit someone
 * else's "already seen". Wrapped because private mode throws on access. */
function hasSeenTour(userId: number): boolean {
  try {
    return localStorage.getItem(SEEN_PREFIX + userId) === "1";
  } catch {
    return true;
  }
}

function markTourSeen(userId: number) {
  try {
    localStorage.setItem(SEEN_PREFIX + userId, "1");
  } catch {
    // Nothing to do; the tour simply offers itself again next visit.
  }
}

/** Starts the tour from anywhere inside the provider (user menu, ⌘K). */
export function useTourLauncher() {
  const ctx = useContext(TourStateContext);
  const router = useRouter();
  const pathname = usePathname();
  const { data: user } = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false });

  return () => {
    if (!ctx) return;
    if (user) markTourSeen(user.id);
    if (pathname !== TOUR_START_PATH) router.push(TOUR_START_PATH);
    ctx.start();
  };
}

/** Fires the tour once for an account that has never seen it, on the dashboard only. */
function useTourAutoStart(start: () => void) {
  const pathname = usePathname();
  const { data: user } = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false });
  const { data: onboarding } = useQuery({
    queryKey: ["onboarding-status"],
    queryFn: () => api.onboardingStatus(),
    staleTime: 30_000,
    retry: false,
  });
  const fired = useRef(false);

  useEffect(() => {
    if (fired.current) return;
    if (pathname !== "/") return;
    if (!user) return;
    if (!onboarding?.onboarded) return;
    if (hasSeenTour(user.id)) return;

    fired.current = true;
    markTourSeen(user.id);
    start();
  }, [pathname, user, onboarding, start]);
}

function TourRunner({ steps, onDone }: { steps: TourStep[]; onDone: () => void }) {
  const [stepIndex, setStepIndex] = useState(0);
  const router = useRouter();
  const pathname = usePathname();
  const step = steps[stepIndex];

  useEffect(() => {
    if (step && step.path !== pathname) router.push(step.path);
  }, [step, pathname, router]);

  const { rect, searching } = useTargetRect(step?.selector, step?.scrollOffset);

  if (!step) return null;

  const next = () => (stepIndex + 1 < steps.length ? setStepIndex(stepIndex + 1) : onDone());
  const prev = () => setStepIndex(Math.max(0, stepIndex - 1));

  return (
    <TourOverlay
      step={step}
      stepNumber={stepIndex + 1}
      totalSteps={steps.length}
      targetRect={rect}
      showCard={!searching}
      onNext={next}
      onPrev={prev}
      onSkip={onDone}
    />
  );
}

/** Mounts the guided product tour around the authenticated app chrome. */
export function TourRoot({ children }: { children: React.ReactNode }) {
  // Cache-only: this has no business adding a request to pages that never
  // needed one. `enabled: false` still subscribes, so the value arrives the
  // moment the dashboard or applications page fetches it.
  const { data: apps } = useQuery({
    queryKey: ["applications"],
    queryFn: () => api.listApplications(),
    enabled: false,
  });
  const steps = useMemo(
    () => buildTour({ hasApplications: (apps?.length ?? 0) > 0 }),
    [apps],
  );

  const [active, setActive] = useState(false);
  const start = useCallback(() => setActive(true), []);
  const stop = useCallback(() => setActive(false), []);

  const value = useMemo<TourState>(() => ({ active, start, skip: stop }), [active, start, stop]);

  useTourAutoStart(start);

  return (
    <TourStateContext.Provider value={value}>
      {children}
      {active && <TourRunner steps={steps} onDone={stop} />}
    </TourStateContext.Provider>
  );
}
