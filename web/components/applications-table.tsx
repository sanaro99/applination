"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Download, ExternalLink, X } from "lucide-react";

import type { Application, ApplicationStatus } from "@/lib/types";
import { api } from "@/lib/api";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ScoreChip, STATUSES, StatusBadge } from "@/components/status-badge";
import { SourceBadge, sourceLabel } from "@/components/source-badge";

function deadlineTone(deadline: string | null): string {
  if (!deadline) return "text-muted-foreground";
  const days = (new Date(deadline).getTime() - Date.now()) / 86_400_000;
  if (days < 0) return "text-red-600 dark:text-red-400";
  if (days <= 3) return "text-amber-600 dark:text-amber-400";
  return "text-foreground";
}

export function ApplicationsTable({
  applications,
}: {
  applications: Application[];
}) {
  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState<ApplicationStatus | "all">(
    "all",
  );
  const [sourceFilter, setSourceFilter] = useState<string>("all");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const qc = useQueryClient();

  const update = useMutation({
    mutationFn: ({ id, status }: { id: number; status: ApplicationStatus }) =>
      api.patchApplication(id, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["applications"] }),
    onError: (e) => toast.error(String(e)),
  });

  const bulk = useMutation({
    mutationFn: (status: ApplicationStatus) =>
      api.bulkUpdateApplications([...selected], { status }),
    onSuccess: (rows) => {
      toast.success(`Updated ${rows.length} application(s)`);
      setSelected(new Set());
      qc.invalidateQueries({ queryKey: ["applications"] });
    },
    onError: (e) => toast.error(String(e)),
  });

  const sources = useMemo(
    () =>
      Array.from(new Set(applications.map((a) => a.source).filter(Boolean))).sort(
        (a, b) => sourceLabel(a).localeCompare(sourceLabel(b)),
      ),
    [applications],
  );

  const term = q.trim().toLowerCase();
  const filtered = useMemo(
    () =>
      applications.filter((a) => {
        if (statusFilter !== "all" && a.status !== statusFilter) return false;
        if (sourceFilter !== "all" && a.source !== sourceFilter) return false;
        if (!term) return true;
        const hay = `${a.company} ${a.title} ${a.location} ${a.tags.join(" ")}`;
        return hay.toLowerCase().includes(term);
      }),
    [applications, statusFilter, sourceFilter, term],
  );

  const allSelected = filtered.length > 0 && filtered.every((a) => selected.has(a.id));
  const someSelected = selected.size > 0;

  function toggleAll() {
    setSelected((prev) => {
      if (filtered.every((a) => prev.has(a.id))) {
        const next = new Set(prev);
        filtered.forEach((a) => next.delete(a.id));
        return next;
      }
      return new Set([...prev, ...filtered.map((a) => a.id)]);
    });
  }

  function toggleOne(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function exportCsv() {
    try {
      await api.exportApplicationsCsv(someSelected ? [...selected] : []);
    } catch (e) {
      toast.error(String(e));
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3">
        <Input
          placeholder="Search company, role, or tag…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="max-w-sm"
        />
        <Select
          value={statusFilter}
          onValueChange={(v) => setStatusFilter(v as ApplicationStatus | "all")}
        >
          <SelectTrigger className="w-40">
            <SelectValue placeholder="Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            {STATUSES.map((s) => (
              <SelectItem key={s} value={s} className="capitalize">
                {s}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={sourceFilter}
          onValueChange={(v) => setSourceFilter(v ?? "all")}
        >
          <SelectTrigger className="w-40">
            <SelectValue placeholder="Source" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All sources</SelectItem>
            {sources.map((s) => (
              <SelectItem key={s} value={s}>
                {sourceLabel(s)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button variant="outline" onClick={exportCsv} className="ml-auto">
          <Download className="size-4" />
          Export {someSelected ? `(${selected.size})` : "all"} CSV
        </Button>
      </div>

      {someSelected && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm">
          <span className="font-medium">{selected.size} selected</span>
          <Select onValueChange={(v) => bulk.mutate(v as ApplicationStatus)}>
            <SelectTrigger className="h-8 w-44">
              <SelectValue placeholder="Set status…" />
            </SelectTrigger>
            <SelectContent>
              {STATUSES.map((s) => (
                <SelectItem key={s} value={s} className="capitalize">
                  Set to {s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setSelected(new Set())}
            className="text-muted-foreground"
          >
            <X className="size-3.5" /> Clear
          </Button>
        </div>
      )}

      <div className="overflow-hidden rounded-lg border border-border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[2.5rem]">
                <Checkbox
                  checked={allSelected}
                  onCheckedChange={toggleAll}
                  aria-label="Select all"
                />
              </TableHead>
              <TableHead className="w-[5rem]">Score</TableHead>
              <TableHead>Company</TableHead>
              <TableHead>Title</TableHead>
              <TableHead className="w-[9rem]">Source</TableHead>
              <TableHead>Tags</TableHead>
              <TableHead className="w-[8rem]">Status</TableHead>
              <TableHead className="w-[9rem]">Deadline</TableHead>
              <TableHead className="w-[9rem]">Applied</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((a, i) => (
              <TableRow
                key={a.id}
                // Anchors the product tour's "open one to see the work" step.
                id={i === 0 ? "tour-first-application" : undefined}
                data-state={selected.has(a.id) ? "selected" : undefined}
              >
                <TableCell>
                  <Checkbox
                    checked={selected.has(a.id)}
                    onCheckedChange={() => toggleOne(a.id)}
                    aria-label={`Select ${a.company}`}
                  />
                </TableCell>
                <TableCell>
                  <ScoreChip score={a.match_score} />
                </TableCell>
                <TableCell className="font-medium">
                  <div className="flex items-center gap-1.5">
                    <Link href={`/applications/${a.id}`} className="hover:underline">
                      {a.company}
                    </Link>
                    {a.url && (
                      <a
                        href={a.url}
                        target="_blank"
                        rel="noreferrer"
                        title="Open job posting"
                        onClick={(e) => e.stopPropagation()}
                        className="text-muted-foreground hover:text-foreground"
                      >
                        <ExternalLink className="size-3.5" />
                      </a>
                    )}
                  </div>
                </TableCell>
                <TableCell className="text-muted-foreground">
                  <Link
                    href={`/applications/${a.id}`}
                    className="hover:text-foreground hover:underline"
                  >
                    {a.title}
                  </Link>
                </TableCell>
                <TableCell>
                  <SourceBadge source={a.source} />
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1">
                    {a.tags.slice(0, 4).map((t) => (
                      <Badge key={t} variant="secondary" className="text-xs">
                        {t}
                      </Badge>
                    ))}
                  </div>
                </TableCell>
                <TableCell>
                  <Select
                    value={a.status}
                    onValueChange={(v) =>
                      update.mutate({ id: a.id, status: v as ApplicationStatus })
                    }
                  >
                    <SelectTrigger className="h-8 w-full">
                      <SelectValue>
                        <StatusBadge status={a.status} />
                      </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      {STATUSES.map((s) => (
                        <SelectItem key={s} value={s} className="capitalize">
                          {s}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </TableCell>
                <TableCell className={`text-sm ${deadlineTone(a.deadline)}`}>
                  {a.deadline ? new Date(a.deadline).toLocaleDateString() : "—"}
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {a.applied_at
                    ? new Date(a.applied_at).toLocaleDateString()
                    : "—"}
                </TableCell>
              </TableRow>
            ))}
            {filtered.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={9}
                  className="h-24 text-center text-sm text-muted-foreground"
                >
                  No applications match the current filters.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
