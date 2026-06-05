"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

/**
 * Redirects a not-yet-set-up install to the onboarding wizard. Mounted once by
 * AppShell. Does not force the user away from /onboarding once complete, so they
 * can revisit setup intentionally.
 */
export function OnboardingGate() {
  const router = useRouter();
  const pathname = usePathname();
  const { data } = useQuery({
    queryKey: ["onboarding-status"],
    queryFn: () => api.onboardingStatus(),
    staleTime: 30_000,
    retry: false,
  });

  useEffect(() => {
    if (!data) return;
    const onOnboarding = pathname.startsWith("/onboarding");
    if (!data.onboarded && !onOnboarding) {
      router.replace("/onboarding");
    }
  }, [data, pathname, router]);

  return null;
}
