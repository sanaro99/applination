"use client";

import { useQuery } from "@tanstack/react-query";
import { Sparkles, X } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const DISMISS_KEY = "applination.demo-banner-dismissed";

/** True when the current session is the shared demo account. */
export function useIsDemo(): boolean {
  const { data } = useQuery({ queryKey: ["me"], queryFn: api.me });
  return data?.is_demo ?? false;
}

/**
 * A standing reminder that the AI in this account is not real.
 *
 * Dismissible, but only for the session rather than permanently: someone who
 * hides it and comes back to Coach an hour later should be told again, since
 * the entire point is that they not mistake a fixture for a model.
 */
export function DemoBanner() {
  const isDemo = useIsDemo();
  // Starts hidden and is revealed by the effect below, so it cannot flash on
  // during hydration for someone who already dismissed it.
  const [dismissed, setDismissed] = useState(true);

  useEffect(() => {
    try {
      setDismissed(sessionStorage.getItem(DISMISS_KEY) === "1");
    } catch {
      // Private mode or blocked storage: showing the notice is the safe side.
      setDismissed(false);
    }
  }, []);

  if (!isDemo || dismissed) return null;

  return (
    <div className="flex shrink-0 items-center gap-2 border-b border-primary/20 bg-primary/10 px-4 py-2 text-xs sm:px-6">
      <Sparkles className="size-3.5 shrink-0 text-primary" />
      <p className="min-w-0 flex-1">
        You are exploring the <strong>John Doe</strong> demo. Everything works,
        but AI responses are simulated rather than live model calls.{" "}
        <a href="/signup" className="underline underline-offset-2">
          Create an account
        </a>{" "}
        to use your own API keys.
      </p>
      <button
        type="button"
        aria-label="Dismiss"
        className="shrink-0 text-muted-foreground hover:text-foreground"
        onClick={() => {
          setDismissed(true);
          try {
            sessionStorage.setItem(DISMISS_KEY, "1");
          } catch {
            // Nothing to do: the banner simply returns on the next navigation.
          }
        }}
      >
        <X className="size-3.5" />
      </button>
    </div>
  );
}

/**
 * Honesty at the point of use. The banner sits at the top of the page and can
 * be dismissed; this sits next to the button that is about to "call a model".
 */
export function SimulatedChip({ className }: { className?: string }) {
  const isDemo = useIsDemo();
  if (!isDemo) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border border-primary/30",
        "bg-primary/10 px-2 py-0.5 text-[10px] font-medium uppercase",
        "tracking-wide text-primary",
        className,
      )}
      title="This account returns canned responses instead of calling a model."
    >
      <Sparkles className="size-2.5" />
      Simulated
    </span>
  );
}
