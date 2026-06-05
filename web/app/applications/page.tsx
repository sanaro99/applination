"use client";

import { Suspense, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { useLatestRuns, anyRunActive } from "@/lib/use-latest-runs";
import { ApplicationsTable } from "@/components/applications-table";
import { ApplicationsKanban } from "@/components/applications-kanban";
import { InboxSync } from "@/components/inbox-sync";

export default function ApplicationsPage() {
  return (
    <Suspense fallback={<Skeleton className="mx-auto h-96 max-w-7xl" />}>
      <ApplicationsView />
    </Suspense>
  );
}

function ApplicationsView() {
  const params = useSearchParams();
  const runId = params.get("run_id");
  const { data: runs } = useLatestRuns();
  const { data, isLoading } = useQuery({
    queryKey: ["applications", runId ?? "all"],
    queryFn: () =>
      api.listApplications(
        runId ? { run_id: Number(runId) } : undefined,
      ),
    // New applications only appear while a run is generating; otherwise this is
    // a static management view served from cache.
    refetchInterval: () => (anyRunActive(runs) ? 4000 : false),
  });

  const applications = useMemo(() => data ?? [], [data]);

  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>
            Applications
            {runId && (
              <span className="ml-2 text-sm font-normal text-muted-foreground">
                · run #{runId}
              </span>
            )}
          </CardTitle>
          <div className="flex items-center gap-3">
            <span className="text-sm text-muted-foreground">
              {applications.length} total
            </span>
            <InboxSync />
          </div>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="table">
            <TabsList>
              <TabsTrigger value="table">Table</TabsTrigger>
              <TabsTrigger value="kanban">Kanban</TabsTrigger>
            </TabsList>
            <TabsContent value="table" className="mt-4">
              {isLoading ? (
                <Skeleton className="h-96 w-full" />
              ) : (
                <ApplicationsTable applications={applications} />
              )}
            </TabsContent>
            <TabsContent value="kanban" className="mt-4">
              {isLoading ? (
                <Skeleton className="h-96 w-full" />
              ) : (
                <ApplicationsKanban applications={applications} />
              )}
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  );
}
