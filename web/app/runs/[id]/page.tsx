"use client";

import { use, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft, CircleStop, ExternalLink, OctagonX } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button, buttonVariants } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, subscribeRun } from "@/lib/api";
import { isRunActive } from "@/lib/use-latest-runs";
import type { PipelineEvent } from "@/lib/types";
import { RankedPool } from "@/components/ranked-pool";

export default function RunDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const runId = Number(id);

  const { data: run } = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.getRun(runId),
    // Poll only while the run is active so its status flips to done/error and
    // the live UI catches up; a finished run never changes.
    refetchInterval: (query) => {
      const r = query.state.data;
      return r && isRunActive(r.status) ? 3000 : false;
    },
  });
  const { data: log, refetch: refetchLog } = useQuery({
    queryKey: ["run-log", runId],
    queryFn: () => api.getRunLog(runId),
    enabled: !!run,
  });
  const { data: apps } = useQuery({
    queryKey: ["applications", runId],
    queryFn: () => api.listApplications({ run_id: runId }),
    refetchInterval: () => (run && isRunActive(run.status) ? 4000 : false),
  });

  const [events, setEvents] = useState<PipelineEvent[]>([]);
  const [stopping, setStopping] = useState(false);
  const closeRef = useRef<null | (() => void)>(null);

  async function requestStop(graceful: boolean) {
    setStopping(true);
    try {
      await api.stopRun(runId, graceful);
      toast.message(
        graceful
          ? "Stopping gracefully — finishing the current application first."
          : "Stopping now — skipping the remaining jobs.",
      );
    } catch (e) {
      setStopping(false);
      toast.error(e instanceof Error ? e.message : String(e));
    }
  }
  // Keyed on status (not the whole `run` object, which gets a new reference on
  // every poll) so the SSE subscription isn't torn down and recreated each tick.
  const status = run?.status;
  useEffect(() => {
    if (!status) return;
    if (status === "running") {
      closeRef.current = subscribeRun(runId, (e) =>
        setEvents((curr) => [...curr.slice(-499), e]),
      );
      return () => closeRef.current?.();
    }
    // Run is queued or finished: grab the latest persisted log once. A queued
    // run's status query keeps polling and will flip to "running", re-running
    // this effect into the SSE branch; a finished run's log is static.
    refetchLog();
  }, [status, runId, refetchLog]);

  if (!run) return <Skeleton className="h-[80svh]" />;

  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <div className="flex items-center justify-between">
        <Link
          href="/runs"
          className={buttonVariants({ variant: "ghost", size: "sm" })}
        >
          <ArrowLeft className="size-4" /> All runs
        </Link>
        <div className="flex items-center gap-2">
          <Badge
            variant={
              run.status === "done"
                ? "secondary"
                : run.status === "running"
                  ? "default"
                  : run.status === "error"
                    ? "destructive"
                    : "outline"
            }
            className="capitalize"
          >
            {run.status}
          </Badge>
          {run.status === "running" && (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => requestStop(true)}
                disabled={stopping}
                title="Finish the application currently being generated, write the tracker, then stop."
              >
                <CircleStop className="size-3" /> Graceful stop
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={() => requestStop(false)}
                disabled={stopping}
                title="Stop as soon as the current job returns. Skips the Excel tracker."
              >
                <OctagonX className="size-3" /> Stop now
              </Button>
            </>
          )}
          <Link
            href={`/applications?run_id=${run.id}`}
            className={buttonVariants({ variant: "outline", size: "sm" })}
          >
            <ExternalLink className="size-3" /> Applications
          </Link>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Run #{run.id}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Field
              label="Started"
              value={new Date(run.started_at).toLocaleString()}
            />
            <Field
              label="Finished"
              value={
                run.finished_at
                  ? new Date(run.finished_at).toLocaleString()
                  : "—"
              }
            />
            <Field label="Jobs found" value={String(run.jobs_found)} />
            <Field
              label="Apps created"
              value={String(run.applications_created)}
            />
            <Field
              label="Mode"
              value={
                [
                  run.dry_run && "dry-run",
                  run.no_pdf && "no-pdf",
                  run.no_cache && "no-cache",
                ]
                  .filter(Boolean)
                  .join(" · ") || "full"
              }
            />
            <Field
              label="Day root"
              value={run.day_root || "—"}
            />
            {run.error && (
              <div className="sm:col-span-2 lg:col-span-4">
                <Field
                  label="Error"
                  value={run.error}
                  className="text-destructive"
                />
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Log</CardTitle>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="log">
            <TabsList>
              <TabsTrigger value="log">File log</TabsTrigger>
              <TabsTrigger value="events">Event timeline</TabsTrigger>
              <TabsTrigger value="apps">
                Applications ({apps?.length ?? 0})
              </TabsTrigger>
              <TabsTrigger value="ranked">Ranked jobs</TabsTrigger>
            </TabsList>
            <TabsContent value="log" className="mt-3">
              <div className="max-h-[60svh] overflow-auto rounded-lg border border-border bg-zinc-950 p-3 font-mono text-xs leading-relaxed text-zinc-200">
                {log?.text ? (
                  <pre className="whitespace-pre-wrap break-words">
                    {log.text}
                  </pre>
                ) : (
                  <span className="text-zinc-500">No log content yet.</span>
                )}
              </div>
            </TabsContent>
            <TabsContent value="events" className="mt-3">
              <div className="max-h-[60svh] overflow-auto rounded-lg border border-border bg-card p-3 text-sm">
                {events.length === 0 ? (
                  <span className="text-muted-foreground">
                    {run.status === "running"
                      ? "Waiting for events…"
                      : "Events are only streamed live for active runs."}
                  </span>
                ) : (
                  <ul className="space-y-1">
                    {events.map((e, i) => (
                      <li key={i} className="font-mono text-xs">
                        <span className="text-muted-foreground">
                          {e.type}
                        </span>{" "}
                        <span>{eventSummary(e)}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </TabsContent>
            <TabsContent value="apps" className="mt-3">
              <div className="space-y-2">
                {(apps ?? []).map((a) => (
                  <Link
                    key={a.id}
                    href={`/applications/${a.id}`}
                    className="flex items-center justify-between rounded-md border border-border/60 px-3 py-2 text-sm hover:bg-muted/40"
                  >
                    <div>
                      <div className="font-medium">{a.company}</div>
                      <div className="text-xs text-muted-foreground">
                        {a.title}
                      </div>
                    </div>
                    <span className="tabular-nums text-sm">
                      {a.match_score}
                    </span>
                  </Link>
                ))}
                {(!apps || apps.length === 0) && (
                  <p className="text-sm text-muted-foreground">
                    No applications generated for this run.
                  </p>
                )}
              </div>
            </TabsContent>
            <TabsContent value="ranked" className="mt-3">
              <RankedPool
                runId={runId}
                active={!!status && isRunActive(status)}
              />
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  );
}

function eventSummary(e: PipelineEvent): string {
  switch (e.type) {
    case "stage_started":
      return `→ ${e.stage}`;
    case "stage_completed":
      return `✓ ${e.stage}${e.duration_s ? ` (${e.duration_s}s)` : ""}`;
    case "job_started":
      return `[${e.idx}/${e.total}] ${e.company} — ${e.title}`;
    case "job_completed":
      return `✓ ${e.company} — ${e.title}${e.error ? " (error)" : ""}`;
    case "job_cached":
      return `cache ${e.company} — ${e.title}`;
    case "done":
      return `${e.applications} applications`;
    case "stopping":
      return e.graceful ? "graceful stop requested" : "stop requested";
    case "cancelled":
      return `${e.graceful ? "stopped" : "cancelled"} — ${e.applications} applications`;
    case "error":
      return e.msg;
    default:
      return "";
  }
}

function Field({
  label,
  value,
  className,
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className={`text-sm ${className ?? ""}`}>{value}</div>
    </div>
  );
}
