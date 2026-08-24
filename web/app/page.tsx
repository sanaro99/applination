"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import {
  ArrowRight,
  Briefcase,
  CalendarClock,
  Play,
  Sparkles,
  Trophy,
} from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { NumberTicker } from "@/components/ui/number-ticker";
import { ShineBorder } from "@/components/ui/shine-border";
import { DotPattern } from "@/components/ui/dot-pattern";
import { BlurFade } from "@/components/ui/blur-fade";
import { api } from "@/lib/api";
import { anyRunActive } from "@/lib/use-latest-runs";
import { cn } from "@/lib/utils";
import { RemindersCard } from "@/components/reminders-card";
import { ProfileStrengthCard } from "@/components/profile-strength-card";
import { SampleDataBanner } from "@/components/sample-data-banner";

export default function DashboardPage() {
  const { data: runs } = useQuery({
    queryKey: ["runs"],
    queryFn: () => api.listRuns(),
    // Only poll while a run is active; otherwise the dashboard is static and
    // served from cache (the global watcher still catches background changes).
    refetchInterval: (query) => (anyRunActive(query.state.data) ? 5000 : false),
  });
  const { data: apps } = useQuery({
    queryKey: ["applications"],
    queryFn: () => api.listApplications(),
    refetchInterval: () => (anyRunActive(runs) ? 5000 : false),
  });

  const totalApps = apps?.length ?? 0;
  const totalRuns = runs?.length ?? 0;
  const avgScore =
    apps && apps.length
      ? Math.round(apps.reduce((s, a) => s + a.match_score, 0) / apps.length)
      : 0;
  const appliedCount =
    apps?.filter((a) => a.status === "applied").length ?? 0;

  const upcoming = (apps ?? [])
    .filter(
      (a) =>
        a.deadline &&
        a.status !== "archived" &&
        a.status !== "rejected",
    )
    .map((a) => ({ app: a, due: new Date(a.deadline as string).getTime() }))
    .filter(({ due }) => due - Date.now() < 14 * 86_400_000)
    .sort((x, y) => x.due - y.due)
    .slice(0, 8);

  const stats = [
    { label: "Applications", value: totalApps, icon: Briefcase },
    { label: "Runs", value: totalRuns, icon: Play },
    { label: "Average score", value: avgScore, icon: Sparkles },
    { label: "Applied", value: appliedCount, icon: Trophy },
  ];

  return (
    <div className="mx-auto max-w-7xl space-y-8">
      <SampleDataBanner />

      <BlurFade delay={0.05}>
        <div className="relative overflow-hidden rounded-2xl border border-border bg-card p-8">
          <ShineBorder
            shineColor={[
              "var(--color-chart-1)",
              "var(--color-chart-2)",
              "var(--color-chart-3)",
            ]}
            borderWidth={1}
          />
          <DotPattern
            className={cn(
              "[mask-image:radial-gradient(400px_circle_at_top_right,white,transparent)]",
            )}
          />
          <div className="relative z-10 flex flex-col gap-4">
            <div className="inline-flex w-fit items-center gap-2 rounded-full border border-border bg-background/60 px-3 py-1 text-xs text-muted-foreground backdrop-blur">
              <span className="relative flex size-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-60" />
                <span className="relative inline-flex size-2 rounded-full bg-primary" />
              </span>
              Applination · AI job pipeline
            </div>
            <h1 className="text-gradient max-w-2xl font-heading text-4xl font-extrabold leading-[1.05] tracking-tight sm:text-5xl">
              Find, tailor, and track every application.
            </h1>
            <p className="max-w-xl text-base text-muted-foreground">
              Run the full pipeline, watch each stage stream live, and dive into
              every generated resume + cover letter from one place.
            </p>
            <div className="flex flex-wrap gap-3">
              <Link
                href="/run"
                className={buttonVariants({ size: "lg" })}
              >
                <Play className="size-4" />
                Start a run
              </Link>
              <Link
                href="/applications"
                className={buttonVariants({ size: "lg", variant: "outline" })}
              >
                Browse applications <ArrowRight className="size-4" />
              </Link>
            </div>
          </div>
        </div>
      </BlurFade>

      <div
        id="tour-dashboard-stats"
        className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
      >
        {stats.map((stat, i) => (
          <BlurFade key={stat.label} delay={0.1 + i * 0.05}>
            <Card className="overflow-hidden">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  {stat.label}
                </CardTitle>
                <stat.icon className="size-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-semibold tabular-nums">
                  <NumberTicker value={stat.value} />
                </div>
              </CardContent>
            </Card>
          </BlurFade>
        ))}
      </div>

      {upcoming.length > 0 && (
        <BlurFade delay={0.12}>
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <CalendarClock className="size-4 text-primary" />
                Upcoming deadlines
              </CardTitle>
            </CardHeader>
            <CardContent className="grid gap-2 sm:grid-cols-2">
              {upcoming.map(({ app: a, due }) => {
                const days = Math.ceil((due - Date.now()) / 86_400_000);
                const tone =
                  days < 0
                    ? "text-red-600 dark:text-red-400"
                    : days <= 3
                      ? "text-amber-600 dark:text-amber-400"
                      : "text-muted-foreground";
                const rel =
                  days < 0
                    ? `${Math.abs(days)}d overdue`
                    : days === 0
                      ? "today"
                      : `in ${days}d`;
                return (
                  <Link
                    key={a.id}
                    href={`/applications/${a.id}`}
                    className="flex items-center justify-between rounded-md border border-border/60 px-3 py-2 text-sm transition-colors hover:bg-muted/40"
                  >
                    <div className="flex min-w-0 flex-col">
                      <span className="truncate font-medium">{a.company}</span>
                      <span className="truncate text-xs text-muted-foreground">
                        {a.title}
                      </span>
                    </div>
                    <span className={cn("shrink-0 text-xs font-medium", tone)}>
                      {rel}
                    </span>
                  </Link>
                );
              })}
            </CardContent>
          </Card>
        </BlurFade>
      )}

      <BlurFade delay={0.13}>
        <div id="tour-profile-strength">
          <ProfileStrengthCard />
        </div>
      </BlurFade>

      <BlurFade delay={0.14}>
        <div id="tour-reminders">
          <RemindersCard />
        </div>
      </BlurFade>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Recent runs</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {(runs ?? []).slice(0, 6).map((r) => (
              <Link
                key={r.id}
                href={`/runs/${r.id}`}
                className="flex items-center justify-between rounded-md border border-border/60 px-3 py-2 text-sm transition-colors hover:bg-muted/40"
              >
                <div className="flex items-center gap-3">
                  <span className="font-mono text-xs text-muted-foreground">
                    #{r.id}
                  </span>
                  <span>{new Date(r.started_at).toLocaleString()}</span>
                </div>
                <span
                  className={cn(
                    "text-xs uppercase tracking-wide",
                    r.status === "running"
                      ? "text-primary"
                      : r.status === "error"
                        ? "text-destructive"
                        : "text-muted-foreground",
                  )}
                >
                  {r.status}
                </span>
              </Link>
            ))}
            {(!runs || runs.length === 0) && (
              <p className="text-sm text-muted-foreground">
                No runs yet. Start one from the Run page.
              </p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Recent applications</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {(apps ?? []).slice(0, 6).map((a) => (
              <Link
                key={a.id}
                href={`/applications/${a.id}`}
                className="flex items-center justify-between rounded-md border border-border/60 px-3 py-2 text-sm transition-colors hover:bg-muted/40"
              >
                <div className="flex flex-col">
                  <span className="font-medium">{a.company}</span>
                  <span className="text-xs text-muted-foreground">
                    {a.title}
                  </span>
                </div>
                <span className="tabular-nums text-sm">{a.match_score}</span>
              </Link>
            ))}
            {(!apps || apps.length === 0) && (
              <p className="text-sm text-muted-foreground">
                No applications yet. Run the pipeline to generate some.
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
