"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { buttonVariants } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api";
import type { RunCompareSummary } from "@/lib/types";

export default function CompareRunsPage() {
  const { data: runs } = useQuery({
    queryKey: ["runs"],
    queryFn: () => api.listRuns(),
  });
  const [a, setA] = useState<number | null>(null);
  const [b, setB] = useState<number | null>(null);

  const { data: cmp, isFetching } = useQuery({
    queryKey: ["compare", a, b],
    queryFn: () => api.compareRuns(a as number, b as number),
    enabled: a != null && b != null && a !== b,
  });

  const runOptions = runs ?? [];

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <div className="flex items-center justify-between">
        <Link
          href="/runs"
          className={buttonVariants({ variant: "ghost", size: "sm" })}
        >
          <ArrowLeft className="size-4" /> All runs
        </Link>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Compare runs</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3">
          <RunPicker label="Run A" value={a} onChange={setA} runs={runOptions} />
          <span className="text-muted-foreground">vs</span>
          <RunPicker label="Run B" value={b} onChange={setB} runs={runOptions} />
          {a != null && a === b && (
            <span className="text-sm text-amber-600 dark:text-amber-400">
              Pick two different runs.
            </span>
          )}
        </CardContent>
      </Card>

      {isFetching && <Skeleton className="h-64 w-full" />}

      {cmp && (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <SummaryCard s={cmp.a} />
            <SummaryCard s={cmp.b} />
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            <CompanyList title="In both runs" items={cmp.shared_companies} />
            <CompanyList title={`Only in #${cmp.a.id}`} items={cmp.only_a} />
            <CompanyList title={`Only in #${cmp.b.id}`} items={cmp.only_b} />
          </div>
        </>
      )}
    </div>
  );
}

function RunPicker({
  label,
  value,
  onChange,
  runs,
}: {
  label: string;
  value: number | null;
  onChange: (v: number) => void;
  runs: { id: number; started_at: string; status: string }[];
}) {
  return (
    <Select
      value={value != null ? String(value) : undefined}
      onValueChange={(v) => v && onChange(Number(v))}
    >
      <SelectTrigger className="w-56">
        <SelectValue placeholder={label} />
      </SelectTrigger>
      <SelectContent>
        {runs.map((r) => (
          <SelectItem key={r.id} value={String(r.id)} className="capitalize">
            #{r.id} · {new Date(r.started_at).toLocaleDateString()} · {r.status}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function SummaryCard({ s }: { s: RunCompareSummary }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-base">Run #{s.id}</CardTitle>
        <Badge variant="outline" className="capitalize">
          {s.status}
        </Badge>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-3 text-sm">
        <Stat label="Jobs found" value={String(s.jobs_found)} />
        <Stat label="Apps created" value={String(s.applications_created)} />
        <Stat label="Avg score" value={String(s.avg_score)} />
        <Stat
          label="Duration"
          value={s.duration_s != null ? `${s.duration_s}s` : "—"}
        />
        <div className="col-span-2">
          <div className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">
            By status
          </div>
          <div className="flex flex-wrap gap-1">
            {Object.entries(s.by_status).length === 0 ? (
              <span className="text-muted-foreground">—</span>
            ) : (
              Object.entries(s.by_status).map(([k, v]) => (
                <Badge key={k} variant="secondary" className="text-xs capitalize">
                  {k}: {v}
                </Badge>
              ))
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="text-lg font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function CompanyList({ title, items }: { title: string; items: string[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">
          {title}{" "}
          <span className="text-muted-foreground">({items.length})</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="max-h-72 space-y-1 overflow-auto">
        {items.length === 0 ? (
          <p className="text-sm text-muted-foreground">None.</p>
        ) : (
          items.map((c) => (
            <div key={c} className="text-sm">
              {c}
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}
