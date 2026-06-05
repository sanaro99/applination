"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { buttonVariants } from "@/components/ui/button";
import { GitCompareArrows } from "lucide-react";
import { api } from "@/lib/api";
import { anyRunActive } from "@/lib/use-latest-runs";

function duration(start: string, end: string | null) {
  if (!end) return "—";
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (ms < 1000) return `${ms}ms`;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}m ${rem}s`;
}

export default function RunsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["runs"],
    queryFn: () => api.listRuns(),
    refetchInterval: (query) => (anyRunActive(query.state.data) ? 3000 : false),
  });
  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Run history</CardTitle>
          <Link
            href="/runs/compare"
            className={buttonVariants({ variant: "outline", size: "sm" })}
          >
            <GitCompareArrows className="size-4" /> Compare runs
          </Link>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-64 w-full" />
          ) : (
            <div className="overflow-hidden rounded-lg border border-border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[5rem]">Run</TableHead>
                    <TableHead>Started</TableHead>
                    <TableHead>Duration</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Jobs found</TableHead>
                    <TableHead>Apps</TableHead>
                    <TableHead>Mode</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(data ?? []).map((r) => (
                    <TableRow key={r.id}>
                      <TableCell>
                        <Link
                          href={`/runs/${r.id}`}
                          className="font-mono text-sm hover:underline"
                        >
                          #{r.id}
                        </Link>
                      </TableCell>
                      <TableCell>
                        {new Date(r.started_at).toLocaleString()}
                      </TableCell>
                      <TableCell>{duration(r.started_at, r.finished_at)}</TableCell>
                      <TableCell>
                        <Badge
                          variant={
                            r.status === "done"
                              ? "secondary"
                              : r.status === "running"
                                ? "default"
                                : r.status === "error"
                                  ? "destructive"
                                  : "outline"
                          }
                          className="capitalize"
                        >
                          {r.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="tabular-nums">
                        {r.jobs_found}
                      </TableCell>
                      <TableCell className="tabular-nums">
                        {r.applications_created}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {[
                          r.dry_run && "dry-run",
                          r.no_pdf && "no-pdf",
                          r.no_cache && "no-cache",
                        ]
                          .filter(Boolean)
                          .join(" · ") || "full"}
                      </TableCell>
                    </TableRow>
                  ))}
                  {(!data || data.length === 0) && (
                    <TableRow>
                      <TableCell
                        colSpan={7}
                        className="h-24 text-center text-sm text-muted-foreground"
                      >
                        No runs yet.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
