"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api, setUnauthorizedHandler } from "@/lib/api";

/** Routes that render without a session. */
const PUBLIC_ROUTES = ["/login", "/signup"];

function isPublic(pathname: string) {
  return PUBLIC_ROUTES.some((r) => pathname === r || pathname.startsWith(`${r}/`));
}

/**
 * Redirects anyone without a session to /login, and installs the handler that
 * catches a session expiring mid-visit.
 *
 * A client component rather than Next middleware because every page in this app
 * is "use client" and the session lives in a cookie the API owns — mirroring
 * the existing OnboardingGate, which is mounted alongside it.
 */
export function AuthGate() {
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["me"],
    queryFn: () => api.me(),
    retry: false,
    // The session outlives any single page view; refetching on every window
    // focus would put a request in front of the user for no benefit.
    staleTime: 5 * 60_000,
  });

  // A 401 from any other endpoint means the session died mid-visit. Send them
  // to /login rather than letting the page fill up with failed queries.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      queryClient.setQueryData(["me"], null);
      if (!isPublic(window.location.pathname)) {
        router.replace(
          `/login?next=${encodeURIComponent(window.location.pathname)}`,
        );
      }
    });
    return () => setUnauthorizedHandler(null);
  }, [router, queryClient]);

  useEffect(() => {
    if (isLoading) return;
    const signedIn = !isError && !!data;
    if (!signedIn && !isPublic(pathname)) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
    // Someone already signed in has no business on the login page.
    if (signedIn && isPublic(pathname)) {
      router.replace("/");
    }
  }, [data, isError, isLoading, pathname, router]);

  return null;
}
