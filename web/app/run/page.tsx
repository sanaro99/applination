"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import {
  AlertCircle,
  Briefcase,
  CheckCircle2,
  CircleStop,
  Loader2,
  OctagonX,
  Play,
  Sparkles,
} from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { ShineBorder } from "@/components/ui/shine-border";
import { MagicCard } from "@/components/ui/magic-card";
import { NumberTicker } from "@/components/ui/number-ticker";
import { BlurFade } from "@/components/ui/blur-fade";
import { api, subscribeRun } from "@/lib/api";
import { useUI } from "@/lib/store";
import type { PipelineEvent } from "@/lib/types";
import {
  StageStepper,
  type StageId,
  type StageState,
} from "@/components/stage-stepper";
import { LogTerminal, type LogLine } from "@/components/log-terminal";

interface LiveJob {
  idx: number;
  total: number;
  company: string;
  title: string;
  score: number;
  done: boolean;
  error: string;
  url?: string;
  source?: string;
  location?: string;
  folder_rel?: string;
}

const INITIAL_STAGES: Record<StageId, StageState> = {
  fetch: "pending",
  rank: "pending",
  tailor: "pending",
  tracker: "pending",
};

export default function RunPage() {
  const router = useRouter();
  const { setActiveRunId } = useUI();
  const [options, setOptions] = useState({
    dry_run: false,
    no_pdf: false,
    no_cache: false,
  });
  const [runId, setRunId] = useState<number | null>(null);
  const [stages, setStages] = useState<Record<StageId, StageState>>(INITIAL_STAGES);
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [jobs, setJobs] = useState<LiveJob[]>([]);
  const [fetchSummary, setFetchSummary] = useState<{
    jobs_found: number;
    duration_s: number;
  } | null>(null);
  const [doneSummary, setDoneSummary] = useState<{
    applications: number;
    jobs_found: number;
    day_root: string;
    dry_run: boolean;
    cancelled?: boolean;
    graceful?: boolean;
  } | null>(null);
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);
  const closeRef = useRef<null | (() => void)>(null);

  useEffect(() => {
    return () => {
      if (closeRef.current) closeRef.current();
    };
  }, []);

  function reset() {
    setStages(INITIAL_STAGES);
    setLogs([]);
    setJobs([]);
    setFetchSummary(null);
    setDoneSummary(null);
    setStopping(false);
  }

  function handleEvent(evt: PipelineEvent) {
    if (evt.type === "stage_started") {
      setStages((s) => ({ ...s, [evt.stage as StageId]: "active" }));
    } else if (evt.type === "stage_completed") {
      setStages((s) => ({ ...s, [evt.stage as StageId]: "done" }));
      if (evt.stage === "fetch") {
        setFetchSummary({
          jobs_found: evt.jobs_found ?? 0,
          duration_s: evt.duration_s ?? 0,
        });
      }
      if (evt.stage === "rank" && evt.top) {
        setJobs(
          evt.top.map((t, i) => ({
            idx: i + 1,
            total: evt.top!.length,
            company: t.company,
            title: t.title,
            score: t.score,
            done: false,
            error: "",
            url: t.url,
            source: t.source,
            location: t.location,
          })),
        );
      }
    } else if (evt.type === "job_started") {
      setJobs((current) => {
        const exists = current.find(
          (j) => j.company === evt.company && j.title === evt.title,
        );
        if (exists) {
          return current.map((j) =>
            j === exists ? { ...j, idx: evt.idx, total: evt.total } : j,
          );
        }
        return [
          ...current,
          {
            idx: evt.idx,
            total: evt.total,
            company: evt.company,
            title: evt.title,
            score: evt.score,
            done: false,
            error: "",
            url: evt.url,
            source: evt.source,
            location: evt.location,
          },
        ];
      });
    } else if (evt.type === "job_completed") {
      setJobs((current) =>
        current.map((j) =>
          j.company === evt.company && j.title === evt.title
            ? {
                ...j,
                done: true,
                error: evt.error || "",
                folder_rel: evt.folder_rel,
              }
            : j,
        ),
      );
    } else if (evt.type === "log") {
      setLogs((l) => [
        ...l.slice(-499),
        { level: evt.level, msg: evt.msg, ts: Date.now() },
      ]);
    } else if (evt.type === "done") {
      setDoneSummary({
        applications: evt.applications,
        jobs_found: evt.jobs_found,
        day_root: evt.day_root,
        dry_run: evt.dry_run,
      });
    } else if (evt.type === "stopping") {
      setStopping(true);
    } else if (evt.type === "cancelled") {
      setStopping(false);
      setDoneSummary({
        applications: evt.applications,
        jobs_found: evt.jobs_found,
        day_root: evt.day_root,
        dry_run: evt.dry_run,
        cancelled: true,
        graceful: evt.graceful,
      });
      // Any stage still mid-flight is no longer running; mark it stopped.
      setStages((s) => {
        const out = { ...s };
        for (const k of Object.keys(out) as StageId[]) {
          if (out[k] === "active") out[k] = "done";
        }
        return out;
      });
    } else if (evt.type === "error") {
      setStages((s) => {
        const out = { ...s };
        for (const k of Object.keys(out) as StageId[]) {
          if (out[k] === "active") out[k] = "error";
        }
        return out;
      });
      toast.error(evt.msg || "Pipeline error");
    }
  }

  async function start() {
    if (starting || runId) return;
    setStarting(true);
    reset();
    try {
      const r = await api.startRun(options);
      setRunId(r.id);
      setActiveRunId(r.id);
      closeRef.current = subscribeRun(r.id, handleEvent, () => {
        toast.error("Lost connection to run stream");
      });
      toast.success(`Run #${r.id} started`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setStarting(false);
    }
  }

  async function requestStop(graceful: boolean) {
    if (runId == null || stopping) return;
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

  const completedJobs = jobs.filter((j) => j.done).length;
  const hasStarted = runId != null;
  const isRunning = hasStarted && !doneSummary;

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      {!hasStarted ? (
        <BlurFade delay={0.05}>
          <Card className="relative overflow-hidden">
            <ShineBorder
              shineColor={[
                "var(--color-chart-1)",
                "var(--color-chart-2)",
                "var(--color-chart-3)",
              ]}
              borderWidth={1}
            />
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Sparkles className="size-5 text-primary" /> Daily run
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <p className="text-sm text-muted-foreground">
                Fetch jobs from all enabled sources, rank with the LLM, tailor
                resumes and cover letters for the top matches, and write today's
                Excel tracker.
              </p>
              <div className="grid gap-4 sm:grid-cols-3">
                <OptionRow
                  label="Dry run"
                  description="Fetch + rank only, no LLM tailoring."
                  checked={options.dry_run}
                  onChange={(v) =>
                    setOptions((o) => ({ ...o, dry_run: v }))
                  }
                />
                <OptionRow
                  label="Skip PDF"
                  description="Produce .docx only — faster."
                  checked={options.no_pdf}
                  onChange={(v) =>
                    setOptions((o) => ({ ...o, no_pdf: v }))
                  }
                />
                <OptionRow
                  label="Ignore cache"
                  description="Re-tailor jobs even if cached."
                  checked={options.no_cache}
                  onChange={(v) =>
                    setOptions((o) => ({ ...o, no_cache: v }))
                  }
                />
              </div>
              <Button onClick={start} disabled={starting} size="lg">
                {starting ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Play className="size-4" />
                )}
                Start run
              </Button>
            </CardContent>
          </Card>
        </BlurFade>
      ) : (
        <>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between gap-3">
              <CardTitle className="flex items-center gap-2">
                Run #{runId}
                {doneSummary?.cancelled ? (
                  <Badge variant="outline" className="gap-1">
                    <OctagonX className="size-3" />
                    {doneSummary.graceful ? "Stopped" : "Cancelled"}
                  </Badge>
                ) : doneSummary ? (
                  <Badge variant="secondary" className="gap-1">
                    <CheckCircle2 className="size-3" /> Done
                  </Badge>
                ) : stopping ? (
                  <Badge variant="outline" className="gap-1">
                    <Loader2 className="size-3 animate-spin" /> Stopping…
                  </Badge>
                ) : (
                  <Badge className="gap-1">
                    <Loader2 className="size-3 animate-spin" /> Running
                  </Badge>
                )}
              </CardTitle>
              {isRunning ? (
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => requestStop(true)}
                    disabled={stopping}
                    title="Finish the application currently being generated, write the tracker, then stop."
                  >
                    <CircleStop className="size-4" /> Graceful stop
                  </Button>
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => requestStop(false)}
                    disabled={stopping}
                    title="Stop as soon as the current job returns. Skips the Excel tracker."
                  >
                    <OctagonX className="size-4" /> Stop now
                  </Button>
                </div>
              ) : (
                doneSummary &&
                !doneSummary.dry_run &&
                doneSummary.applications > 0 && (
                  <Link
                    href={`/applications?run_id=${runId}`}
                    className={buttonVariants()}
                  >
                    View applications
                  </Link>
                )
              )}
            </CardHeader>
            <CardContent className="space-y-4">
              <StageStepper stageStates={stages} />
              <div className="grid gap-3 sm:grid-cols-3">
                <StatTile
                  label="Jobs fetched"
                  value={fetchSummary?.jobs_found ?? 0}
                />
                <StatTile label="Top matches" value={jobs.length} />
                <StatTile label="Tailored" value={completedJobs} />
              </div>
            </CardContent>
          </Card>

          <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <Briefcase className="size-4" /> Top matches
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {jobs.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    Waiting for ranking to finish…
                  </p>
                ) : (
                  <div className="grid gap-2 max-h-[28rem] overflow-auto pr-1">
                    {jobs.map((j, i) => (
                      <MagicCard
                        key={`${j.company}-${j.title}-${i}`}
                        gradientColor="var(--color-accent)"
                        gradientFrom="var(--color-chart-1)"
                        gradientTo="var(--color-chart-3)"
                      >
                        <div className="flex items-center justify-between gap-3 p-3">
                          <div className="min-w-0">
                            <div className="flex items-center gap-2 text-sm font-medium">
                              <span className="truncate">{j.company}</span>
                              <span className="truncate text-muted-foreground">
                                {j.title}
                              </span>
                            </div>
                            <div className="text-xs text-muted-foreground">
                              {j.location || j.source}
                            </div>
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-sm tabular-nums">
                              {j.score}
                            </span>
                            {j.error ? (
                              <AlertCircle className="size-4 text-destructive" />
                            ) : j.done ? (
                              <CheckCircle2 className="size-4 text-emerald-500" />
                            ) : (
                              <Loader2 className="size-4 animate-spin text-muted-foreground" />
                            )}
                          </div>
                        </div>
                      </MagicCard>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Live log</CardTitle>
              </CardHeader>
              <CardContent>
                <LogTerminal lines={logs} />
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

function OptionRow({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-lg border border-border bg-card p-3">
      <div>
        <Label className="text-sm">{label}</Label>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
      <Switch checked={checked} onCheckedChange={onChange} />
    </div>
  );
}

function StatTile({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="text-2xl font-semibold tabular-nums">
        <NumberTicker value={value} />
      </div>
    </div>
  );
}
