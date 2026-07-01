"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2, MailCheck, MailWarning } from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
  SheetFooter,
} from "@/components/ui/sheet";
import { api } from "@/lib/api";
import type { InboxSyncCandidate } from "@/lib/types";
import {
  classifyEmail,
  getEngine,
  webgpuSupported,
} from "@/lib/webllm-classify";

type Phase =
  | "idle"
  | "fetching"
  | "loading-model"
  | "classifying"
  | "done"
  | "error"
  | "unsupported";

interface ActivityRow {
  mid: string;
  company: string;
  title: string;
  status: "classifying" | "done";
  category?: string;
  confidence?: number;
  transition?: { old: string; new: string } | null;
  skipped?: boolean;
}

const CATEGORY_LABEL: Record<string, string> = {
  auto_ack: "acknowledged",
  interview: "interview",
  rejection: "rejection",
  offer: "offer",
  other: "no signal",
};

/**
 * "Sync inbox" control: fetches candidate emails from the connected Gmail
 * account, classifies each one locally in the browser (WebLLM — see
 * lib/webllm-classify.ts) so a simple 5-category call never hits a full
 * cloud LLM, and shows live progress instead of a plain spinner.
 */
export function InboxSync() {
  const qc = useQueryClient();
  const { data: status } = useQuery({
    queryKey: ["inbox-status"],
    queryFn: () => api.inboxStatus(),
    staleTime: 60_000,
  });

  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [modelProgress, setModelProgress] = useState<{ pct: number; text: string } | null>(null);
  const [rows, setRows] = useState<ActivityRow[]>([]);
  const [counts, setCounts] = useState({ scanned: 0, matched: 0, classified: 0 });
  const [errorMsg, setErrorMsg] = useState("");

  async function runSync() {
    setOpen(true);
    setRows([]);
    setErrorMsg("");
    setModelProgress(null);
    setCounts({ scanned: 0, matched: 0, classified: 0 });

    if (!webgpuSupported()) {
      setPhase("unsupported");
      return;
    }

    setPhase("fetching");
    let candidates: InboxSyncCandidate[];
    try {
      const res = await api.inboxSyncCandidates();
      candidates = res.candidates;
      setCounts({ scanned: res.scanned, matched: res.matched, classified: 0 });
    } catch (e) {
      setPhase("error");
      setErrorMsg(String(e));
      return;
    }

    if (candidates.length === 0) {
      setPhase("done");
      toast.success("Inbox synced — no new messages to review.");
      qc.invalidateQueries({ queryKey: ["inbox-status"] });
      return;
    }

    setPhase("loading-model");
    let engine;
    try {
      engine = await getEngine((r) => setModelProgress({ pct: r.progress, text: r.text }));
    } catch (e) {
      setPhase("error");
      setErrorMsg(`Could not load the in-browser model: ${e}`);
      return;
    }

    setPhase("classifying");
    let updatesCount = 0;
    for (const c of candidates) {
      setRows((prev) => [
        ...prev,
        { mid: c.mid, company: c.company, title: c.title, status: "classifying" },
      ]);
      const result = await classifyEmail(engine, c);
      let applyResult;
      try {
        applyResult = await api.inboxSyncApply({
          mid: c.mid,
          application_id: c.application_id,
          from_email: c.from_email,
          date: c.date,
          category: result.category,
          confidence: result.confidence,
          summary: result.summary,
          interview_date: result.interview_date,
        });
      } catch (e) {
        console.error("apply failed", e);
        applyResult = { update: null, skipped_low_confidence: false };
      }
      setCounts((prev) => ({ ...prev, classified: prev.classified + 1 }));
      setRows((prev) =>
        prev.map((r) =>
          r.mid === c.mid
            ? {
                ...r,
                status: "done",
                category: result.category,
                confidence: result.confidence,
                transition: applyResult.update
                  ? { old: applyResult.update.old_status, new: applyResult.update.new_status }
                  : null,
                skipped: applyResult.skipped_low_confidence,
              }
            : r,
        ),
      );
      if (applyResult.update) updatesCount += 1;
    }

    setPhase("done");
    toast.success(
      updatesCount === 0
        ? `Inbox synced — ${candidates.length} classified, no status changes.`
        : `Inbox synced — ${updatesCount} application${updatesCount === 1 ? "" : "s"} updated.`,
    );
    qc.invalidateQueries({ queryKey: ["applications"] });
    qc.invalidateQueries({ queryKey: ["inbox-status"] });
  }

  if (status && !status.configured) {
    return (
      <Link
        href="/config"
        className={buttonVariants({ variant: "ghost", size: "sm" })}
        title="Connect Gmail in config to enable inbox sync"
      >
        <MailWarning className="size-4" />
        Connect inbox
      </Link>
    );
  }

  const busy = phase !== "idle" && phase !== "done" && phase !== "error" && phase !== "unsupported";

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        onClick={runSync}
        disabled={busy}
        title={
          status?.last_sync
            ? `Last synced ${new Date(status.last_sync + "Z").toLocaleString()}`
            : "Scan your inbox for recruiter replies"
        }
      >
        {busy ? <Loader2 className="size-4 animate-spin" /> : <MailCheck className="size-4" />}
        Sync inbox
      </Button>

      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent className="flex w-full flex-col gap-0 sm:max-w-lg">
          <SheetHeader>
            <SheetTitle>Sync inbox</SheetTitle>
            <SheetDescription>
              {phase === "fetching" && "Fetching Gmail…"}
              {phase === "loading-model" &&
                `Loading the in-browser classifier${modelProgress ? ` — ${Math.round(modelProgress.pct * 100)}%` : ""}…`}
              {phase === "classifying" && "Classifying messages locally in your browser…"}
              {phase === "done" && "Done."}
              {phase === "unsupported" &&
                "Your browser doesn't support in-browser AI (WebGPU) — try Chrome or Edge 113+."}
              {phase === "error" && "Something went wrong."}
            </SheetDescription>
          </SheetHeader>

          {phase === "loading-model" && modelProgress && (
            <div className="px-4">
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-primary transition-all"
                  style={{ width: `${Math.round(modelProgress.pct * 100)}%` }}
                />
              </div>
              <p className="mt-1 truncate text-xs text-muted-foreground">{modelProgress.text}</p>
            </div>
          )}

          {errorMsg && (
            <p className="px-4 text-sm text-red-600 dark:text-red-400">{errorMsg}</p>
          )}

          <ScrollArea className="min-h-0 flex-1">
            <div className="flex flex-col gap-2 p-4">
              {rows.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  {phase === "fetching" ? "Looking for new messages…" : "No activity yet."}
                </p>
              ) : (
                rows.map((r) => (
                  <div
                    key={r.mid}
                    className="flex flex-wrap items-center gap-2 rounded-md border border-border/60 p-2.5 text-sm"
                  >
                    {r.status === "classifying" ? (
                      <Loader2 className="size-3.5 shrink-0 animate-spin text-muted-foreground" />
                    ) : (
                      <MailCheck className="size-3.5 shrink-0 text-muted-foreground" />
                    )}
                    <span className="min-w-0 flex-1 truncate">
                      <span className="font-medium">{r.company}</span> — {r.title}
                    </span>
                    {r.status === "classifying" ? (
                      <Badge variant="outline" className="text-xs">
                        classifying…
                      </Badge>
                    ) : (
                      <>
                        <Badge variant="outline" className="text-xs">
                          {CATEGORY_LABEL[r.category ?? "other"] ?? r.category}
                          {typeof r.confidence === "number" && ` (${Math.round(r.confidence * 100)}%)`}
                        </Badge>
                        {r.transition ? (
                          <Badge className="text-xs">
                            {r.transition.old} → {r.transition.new}
                          </Badge>
                        ) : r.skipped ? (
                          <Badge variant="ghost" className="text-xs text-muted-foreground">
                            low confidence — skipped
                          </Badge>
                        ) : (
                          <Badge variant="ghost" className="text-xs text-muted-foreground">
                            no change
                          </Badge>
                        )}
                      </>
                    )}
                  </div>
                ))
              )}
            </div>
          </ScrollArea>

          <SheetFooter className="flex-row items-center justify-between border-t border-border/60">
            <span className="text-xs text-muted-foreground">
              {counts.scanned} scanned · {counts.matched} matched · {counts.classified} classified
            </span>
            <Button size="sm" variant="outline" onClick={() => setOpen(false)}>
              Close
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </>
  );
}
