"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, Loader2, XCircle, Zap } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type { ProviderTestResult } from "@/lib/types";
import { cn } from "@/lib/utils";

export function ProvidersPanel() {
  const { data: providers, isLoading } = useQuery({
    queryKey: ["providers"],
    queryFn: () => api.listProviders(),
  });
  const [results, setResults] = useState<Record<string, ProviderTestResult>>({});
  const [testing, setTesting] = useState<string | null>(null);

  const test = useMutation({
    mutationFn: (provider: string) => api.testProvider(provider),
    onMutate: (provider) => setTesting(provider),
    onSuccess: (r) => setResults((prev) => ({ ...prev, [r.provider]: r })),
    onSettled: () => setTesting(null),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Zap className="size-4 text-primary" /> LLM providers
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {isLoading ? (
          <Skeleton className="h-32 w-full" />
        ) : (providers ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No providers found in config.yaml.
          </p>
        ) : (
          (providers ?? []).map((p) => {
            const r = results[p.name];
            return (
              <div
                key={p.name}
                className="flex flex-wrap items-center gap-3 rounded-md border border-border/60 p-3"
              >
                <div className="flex min-w-0 flex-1 items-center gap-2">
                  <span className="font-medium capitalize">{p.name}</span>
                  {p.role !== "available" && (
                    <Badge variant="outline" className="text-xs capitalize">
                      {p.role}
                    </Badge>
                  )}
                  {p.model && (
                    <span className="truncate font-mono text-xs text-muted-foreground">
                      {p.model}
                    </span>
                  )}
                  {!p.configured && (
                    <Badge variant="outline" className="text-xs text-amber-600 dark:text-amber-400">
                      no api key
                    </Badge>
                  )}
                </div>
                {r && (
                  <span
                    className={cn(
                      "flex items-center gap-1 text-xs",
                      r.ok
                        ? "text-emerald-600 dark:text-emerald-400"
                        : "text-red-600 dark:text-red-400",
                    )}
                  >
                    {r.ok ? (
                      <>
                        <CheckCircle2 className="size-3.5" /> ok · {r.latency_ms}ms
                      </>
                    ) : (
                      <>
                        <XCircle className="size-3.5" />
                        <span className="max-w-60 truncate" title={r.error}>
                          {r.error || "failed"}
                        </span>
                      </>
                    )}
                  </span>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => test.mutate(p.name)}
                  disabled={testing === p.name}
                >
                  {testing === p.name ? (
                    <Loader2 className="size-3.5 animate-spin" />
                  ) : null}
                  Test
                </Button>
              </div>
            );
          })
        )}
        <p className="pt-1 text-xs text-muted-foreground">
          A test makes one tiny real API call to check connectivity and latency.
        </p>
      </CardContent>
    </Card>
  );
}
