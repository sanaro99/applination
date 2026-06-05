"use client";

import { useEffect, useMemo, useState } from "react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { fileUrl } from "@/lib/api";
import type { ResumeVersion } from "@/lib/types";
import { cn } from "@/lib/utils";
import { diffLines, flattenResume, type DiffLine } from "@/lib/resume-diff";

function versionLabel(v: ResumeVersion): string {
  // resume.docx -> "Original", resume.v2.docx -> "v2"
  const m = v.docx.match(/\.v(\d+)\.docx$/);
  return m ? `v${m[1]}` : "Original";
}

async function fetchResume(
  folderRel: string,
  jsonName: string,
): Promise<Record<string, unknown>> {
  const res = await fetch(fileUrl(folderRel, jsonName), { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export function ResumeDiff({
  folderRel,
  versions,
}: {
  folderRel: string;
  versions: ResumeVersion[];
}) {
  const withJson = useMemo(
    () => versions.filter((v) => v.json),
    [versions],
  );

  const [fromName, setFromName] = useState<string>("");
  const [toName, setToName] = useState<string>("");

  // Default to comparing the two most recent versions.
  useEffect(() => {
    if (withJson.length < 2) return;
    const last = withJson[withJson.length - 1];
    const prev = withJson[withJson.length - 2];
    setToName((cur) => cur || (last.json as string));
    setFromName((cur) => cur || (prev.json as string));
  }, [withJson]);

  const [diff, setDiff] = useState<DiffLine[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!fromName || !toName) return;
    let cancelled = false;
    setDiff(null);
    setErr(null);
    Promise.all([
      fetchResume(folderRel, fromName),
      fetchResume(folderRel, toName),
    ])
      .then(([a, b]) => {
        if (cancelled) return;
        setDiff(diffLines(flattenResume(a), flattenResume(b)));
      })
      .catch(() => {
        if (!cancelled) setErr("Could not load resume versions to compare.");
      });
    return () => {
      cancelled = true;
    };
  }, [folderRel, fromName, toName]);

  if (withJson.length < 2) {
    return (
      <p className="text-xs text-muted-foreground">
        Generate at least one tweak to compare versions.
      </p>
    );
  }

  const changed = diff?.filter((d) => d.type !== "same").length ?? 0;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <VersionSelect
          value={fromName}
          onChange={setFromName}
          options={withJson}
          label="From"
        />
        <span className="text-muted-foreground">→</span>
        <VersionSelect
          value={toName}
          onChange={setToName}
          options={withJson}
          label="To"
        />
        {diff && (
          <span className="ml-auto text-muted-foreground">
            {changed === 0 ? "No changes" : `${changed} line(s) changed`}
          </span>
        )}
      </div>

      {err && <p className="text-xs text-destructive">{err}</p>}
      {!diff && !err && <Skeleton className="h-40 w-full" />}
      {diff && (
        <div className="max-h-[60svh] overflow-auto rounded-md border border-border bg-muted/30 p-2 font-mono text-xs leading-relaxed">
          {diff.map((d, i) => (
            <DiffRow key={i} line={d} />
          ))}
        </div>
      )}
    </div>
  );
}

function VersionSelect({
  value,
  onChange,
  options,
  label,
}: {
  value: string;
  onChange: (v: string) => void;
  options: ResumeVersion[];
  label: string;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-muted-foreground">{label}</span>
      <Select value={value} onValueChange={(v) => v && onChange(v)}>
        <SelectTrigger className="h-7 w-28">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((v) => (
            <SelectItem key={v.json as string} value={v.json as string}>
              {versionLabel(v)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function DiffRow({ line }: { line: DiffLine }) {
  const isHeader = line.text.startsWith("§");
  const prefix =
    line.type === "add" ? "+ " : line.type === "remove" ? "− " : "  ";
  return (
    <div
      className={cn(
        "whitespace-pre-wrap rounded px-1.5 py-0.5",
        line.type === "add" &&
          "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
        line.type === "remove" &&
          "bg-red-500/15 text-red-700 dark:text-red-300",
        line.type === "same" && "text-muted-foreground",
        isHeader && line.type === "same" && "mt-1 font-semibold text-foreground",
      )}
    >
      {prefix}
      {line.text.replace(/^§ /, "")}
    </div>
  );
}
