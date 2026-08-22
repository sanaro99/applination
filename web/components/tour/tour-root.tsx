"use client";

import { useQuery } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { NextStep, NextStepProvider, useNextStep } from "nextstepjs";
import { useEffect, useMemo, useRef } from "react";

import { api } from "@/lib/api";
import { TourCard } from "@/components/tour/tour-card";
import {
  TOUR_NAME,
  TOUR_START_PATH,
  buildTour,
} from "@/components/tour/tour-steps";
// buildTour's return type (TourStep[]) is structurally a Step[] with an
// extra optional field, so it satisfies NextStep's `steps` prop as-is.

const SEEN_PREFIX = "applination.tour.v1.seen.";

/**
 * Per-user so switching accounts on one browser does not inherit someone
 * else's "already seen". Wrapped because private mode throws on access.
 */
function hasSeenTour(userId: number): boolean {
  try {
    return localStorage.getItem(SEEN_PREFIX + userId) === "1";
  } catch {
    // Unreadable storage: treat as seen. Auto-starting a tour on every single
    // page load is far worse than never auto-starting it.
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
  const { startNextStep } = useNextStep();
  const router = useRouter();
  const pathname = usePathname();
  const { data: user } = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false });

  return () => {
    // Replaying implies they have seen it, so it should not auto-start later.
    if (user) markTourSeen(user.id);
    // The tour walks forward from the dashboard. Launching it from elsewhere
    // has to land there first; the opening step is centered and unanchored, so
    // it reads correctly while the route is still settling.
    if (pathname !== TOUR_START_PATH) router.push(TOUR_START_PATH);
    startNextStep(TOUR_NAME);
  };
}

/**
 * Fires the tour once for an account that has never seen it.
 *
 * Deliberately only on the dashboard: the tour's first step describes the
 * dashboard, and starting it wherever the user happened to land would mean
 * navigating them away from the page they asked for.
 */
function TourAutoStart() {
  const { startNextStep } = useNextStep();
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
    // Not while OnboardingGate is about to redirect to the wizard.
    if (!onboarding?.onboarded) return;
    if (hasSeenTour(user.id)) return;

    fired.current = true;
    // Marked on start, not on finish: a mid-tour reload loses the step index,
    // and restarting from step one every reload is worse than ending early.
    markTourSeen(user.id);
    startNextStep(TOUR_NAME);
  }, [pathname, user, onboarding, startNextStep]);

  return null;
}

/**
 * Mounts the guided product tour around the authenticated app chrome.
 *
 * Steps are rebuilt whenever the account's data changes so that steps with
 * nothing to point at drop out — nextstepjs leaves the card stranded at its
 * previous position if a selector never resolves, so filtering up front is
 * what keeps an empty account from seeing a spotlight on nothing.
 */
export function TourRoot({ children }: { children: React.ReactNode }) {
  // Cache-only: TourRoot mounts on every authenticated page, and it has no
  // business adding a request to pages that never needed one. `enabled: false`
  // still subscribes to this key, so the value arrives the moment the
  // dashboard or the applications page fetches it — and the tour always passes
  // through the dashboard before it reaches the step that depends on this.
  const { data: apps } = useQuery({
    queryKey: ["applications"],
    queryFn: () => api.listApplications(),
    enabled: false,
  });

  const steps = useMemo(
    () => buildTour({ hasApplications: (apps?.length ?? 0) > 0 }),
    [apps],
  );

  return (
    <NextStepProvider>
      <NextStep
        steps={[{ tour: TOUR_NAME, steps }]}
        cardComponent={TourCard}
        // Indigo-tinted scrim rather than flat black, matching the accent.
        shadowRgb="49, 46, 129"
        shadowOpacity="0.65"
        // The spotlight is an explanation, not a task: clicking the page
        // mid-step would desync the tour from what is on screen.
        clickThroughOverlay={false}
        disableConsoleLogs
      >
        <TourAutoStart />
        {children}
      </NextStep>
    </NextStepProvider>
  );
}
