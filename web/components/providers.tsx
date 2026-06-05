"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/sonner";
import { useState } from "react";

export function Providers({ children }: { children: React.ReactNode }) {
  const [qc] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // Revisiting a page within this window serves instantly from cache
            // instead of refetching on every navigation. Freshness for live
            // data comes from the (adaptive) refetchIntervals, not refetch-on-
            // mount — which is why both refetch triggers below are disabled.
            staleTime: 30_000,
            gcTime: 5 * 60_000,
            refetchOnMount: false,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );
  return (
    <ThemeProvider attribute="class" defaultTheme="dark" enableSystem={false}>
      <QueryClientProvider client={qc}>
        <TooltipProvider delay={200}>
          {children}
          <Toaster position="top-right" richColors />
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
