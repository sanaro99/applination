"use client";

import { useDeferredValue, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { ArrowUpRight, Bookmark, Check, FileText, Loader2, MapPin, Pause, Play, Search, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { FeedJob, FeedQuery } from "@/lib/types";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

function date(value: string | null) {
  if (!value) return "Not checked yet";
  return new Date(/Z$|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`).toLocaleString();
}
function safeUrl(value: string) {
  try { const url = new URL(value); return ["https:", "http:"].includes(url.protocol) ? url.href : null; } catch { return null; }
}

function JobCard({ job }: { job: FeedJob }) {
  const qc = useQueryClient();
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["jobs"] }); void qc.invalidateQueries({ queryKey: ["applications"] }); };
  const update = useMutation({
    mutationFn: (body: { saved?: boolean; dismissed?: boolean; applied?: boolean }) => api.updateJob(job.id, body),
    onSuccess: (_, body) => { refresh(); if (body.dismissed) toast("Job dismissed", { action: { label: "Undo", onClick: () => update.mutate({ dismissed: false }) } }); },
    onError: e => toast.error(String(e)),
  });
  const generate = useMutation({ mutationFn: () => api.generateJob(job.id), onSuccess: () => { refresh(); toast.success("Documents queued. You can keep browsing."); }, onError: e => toast.error(String(e)) });
  const busy = job.generation?.state === "queued" || job.generation?.state === "running";
  const href = safeUrl(job.url);
  return <article className="rounded-xl border border-border bg-card p-5 shadow-sm transition-colors hover:border-primary/35 sm:p-6">
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0 space-y-2">
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground"><span className="font-medium text-foreground">{job.company}</span><span>· {job.source}</span>{job.stale && <Badge variant="outline">Check freshness</Badge>}{!job.active && <Badge variant="secondary">No longer listed</Badge>}</div>
        <h2 className="font-heading text-xl font-semibold tracking-tight">{job.title}</h2>
        <p className="flex items-center gap-1.5 text-sm text-muted-foreground"><MapPin className="size-3.5 shrink-0" />{job.location || "Location unspecified"}{job.remote && " · Remote"}</p>
      </div>
      <Button size="icon" variant={job.saved ? "secondary" : "ghost"} disabled={update.isPending} aria-label={`${job.saved ? "Unsave" : "Save"} ${job.title} at ${job.company}`} onClick={() => update.mutate({ saved: !job.saved })}><Bookmark className={cn("size-4", job.saved && "fill-current")} /></Button>
    </div>
    <div className="my-4 rounded-lg bg-muted/40 px-3 py-2.5"><p className="text-sm leading-relaxed">{job.reason || "Matched to your saved search."}</p><p className="mt-1 text-xs text-muted-foreground">{job.scoring === 'historical' ? 'Historical fit index' : 'Rules match index'} {job.score} / 100</p></div>
    {job.description && <details className="mb-4 text-sm"><summary className="w-fit cursor-pointer text-muted-foreground hover:text-foreground">Read job description</summary><p className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap leading-relaxed">{job.description}</p></details>}
    <p className="mb-4 text-xs text-muted-foreground">{job.posted_at ? `Posted ${date(job.posted_at)}` : `First seen ${date(job.first_seen)}`} · Last checked {date(job.last_checked)}</p>
    {job.generation?.error && <p role="alert" className="mb-3 text-sm text-destructive">{job.generation.error}</p>}
    <div className="flex flex-wrap items-center gap-2">
      {href && <a href={href} target="_blank" rel="noopener noreferrer" className={buttonVariants({ size: "sm", variant: "outline" })}>View posting <ArrowUpRight className="size-3.5" /></a>}
      {job.application_id ? <Link href={`/applications/${job.application_id}`} className={buttonVariants({ size: "sm" })}>Open application</Link> : <Button size="sm" disabled={busy || generate.isPending || !job.can_generate || !job.active} onClick={() => generate.mutate()}>{busy || generate.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <FileText className="size-3.5" />}{busy ? job.generation?.state === "queued" ? "Documents queued" : "Generating documents" : job.generation?.state === "error" ? "Retry documents" : "Generate documents"}</Button>}
      {job.generation && <Link href={`/runs/${job.generation.run_id}`} className="px-2 text-xs text-muted-foreground underline underline-offset-4">View progress</Link>}
      {!job.applied && <Button size="sm" variant="ghost" disabled={update.isPending} onClick={() => update.mutate({ applied: true })}><Check className="size-3.5" />Mark applied</Button>}
      <Button size="sm" variant="ghost" disabled={update.isPending} onClick={() => update.mutate({ dismissed: !job.dismissed })}><X className="size-3.5" />{job.dismissed ? "Undo dismissal" : "Dismiss"}</Button>
    </div>
    {!job.can_generate && !job.application_id && <p className="mt-3 text-xs text-muted-foreground">This source has a summary only. <Link href="/single" className="underline">Add the full description</Link> to generate documents.</p>}
  </article>;
}

export default function JobsPage() {
  const [q, setQ] = useState("");
  const query = useDeferredValue(q);
  const [view, setView] = useState<FeedQuery["view"]>("recommended");
  const [sort, setSort] = useState<FeedQuery["sort"]>("match");
  const [remote, setRemote] = useState(false);
  const [offset, setOffset] = useState(0);
  const qc = useQueryClient();
  const jobs = useQuery({ queryKey: ["jobs", { query, view, sort, remote, offset }], queryFn: () => api.listJobs({ q: query, view, sort, remote, offset }), refetchInterval: 30000 });
  const status = useQuery({ queryKey: ["discovery"], queryFn: api.discoveryStatus, refetchInterval: 30000 });
  const toggle = useMutation({ mutationFn: () => api.setDiscovery(!status.data?.enabled), onSuccess: () => qc.invalidateQueries({ queryKey: ["discovery"] }), onError: e => toast.error(String(e)) });
  const sources = status.data?.sources ?? [];
  const active = status.data?.enabled && status.data?.administrator_enabled;
  return <div className="mx-auto max-w-5xl space-y-6">
    <header id="tour-jobs-feed" className="space-y-4 rounded-2xl border border-border bg-card p-6 sm:p-8">
      <div className="flex flex-wrap items-start justify-between gap-4"><div className="space-y-2"><div className="flex items-center gap-2 text-xs font-medium uppercase tracking-widest text-primary"><span className={cn("size-2 rounded-full", active ? "bg-emerald-500" : "bg-muted-foreground")} />Your next opportunity</div><h1 className="font-heading text-3xl font-semibold tracking-tight">Jobs worth a closer look.</h1><p className="max-w-xl text-sm leading-relaxed text-muted-foreground">Discover jobs continuously. Choose the ones you like, then generate your resume and cover letter.</p></div><Button variant="outline" size="sm" disabled={!status.data || toggle.isPending} onClick={() => toggle.mutate()}>{status.data?.enabled ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}{status.data?.enabled ? "Pause discovery" : "Resume discovery"}</Button></div>
      <div className="flex flex-wrap gap-x-5 gap-y-2 border-t pt-4 text-xs text-muted-foreground"><span>{active ? sources.some(s => s.fetching) ? "Checking sources…" : "Checks about every 10 minutes" : status.data?.enabled ? "Background discovery is paused by the administrator" : "Discovery paused"}</span><span>Discovery uses no AI credits</span><Link href="/config" className="underline underline-offset-4">Search preferences</Link></div>
      <details className="text-xs text-muted-foreground"><summary className="cursor-pointer">{sources.length} sources · {sources.filter(s => s.error).length} need attention</summary><div className="mt-3 max-h-64 space-y-2 overflow-auto">{sources.map((s, i) => <p key={`${s.kind}-${i}`}><span className="font-medium text-foreground">{s.name}</span> · {s.kind} · {s.error || `Last checked ${date(s.last_success)}`} · Next eligible check {date(s.next_due)}</p>)}{!sources.length && <p>Your sources will appear after your saved search is picked up. Existing jobs remain available below.</p>}</div></details>
    </header>
    <div id="tour-jobs-actions" className="space-y-3"><div className="relative"><Search className="pointer-events-none absolute left-3 top-3 size-4 text-muted-foreground" /><Input aria-label="Search jobs" className="pl-9" placeholder="Search role, company or location" value={q} onChange={e => { setQ(e.target.value); setOffset(0); }} /></div>
      <div className="flex flex-wrap items-center gap-3"><select aria-label="Job collection" className="h-9 rounded-md border bg-background px-3 text-sm" value={view} onChange={e => { setView(e.target.value as FeedQuery["view"]); setOffset(0); }}>{[['recommended','Recommended'],['saved','Saved'],['applied','Applied'],['dismissed','Dismissed'],['all','All jobs']].map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select><select aria-label="Sort jobs" className="h-9 rounded-md border bg-background px-3 text-sm" value={sort} onChange={e => { setSort(e.target.value as FeedQuery["sort"]); setOffset(0); }}><option value="match">Best match</option><option value="newest">Newest first</option></select><label className="flex items-center gap-2 text-sm text-muted-foreground"><input type="checkbox" checked={remote} onChange={e => { setRemote(e.target.checked); setOffset(0); }} />Remote only</label><Link href="/single" className="ml-auto text-sm text-primary underline underline-offset-4">Add a job yourself</Link></div>
    </div>
    {(jobs.error || status.error) && <p role="alert" className="rounded-lg border border-destructive/30 p-4 text-sm text-destructive">{String(jobs.error || status.error)} <button onClick={() => { void jobs.refetch(); void status.refetch(); }} className="underline">Retry</button></p>}
    {jobs.isPending ? <p role="status" className="flex items-center gap-2 py-12 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" />Loading your jobs…</p> : !jobs.error && !jobs.data?.items.length ? <div className="rounded-xl border border-dashed p-10 text-center"><h2 className="font-heading text-xl font-medium">{view === 'recommended' ? 'Your next matches will appear here.' : 'No jobs in this collection yet.'}</h2><p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">{q ? 'Try another search or collection.' : view === 'recommended' ? 'Check your search preferences and source status above. You can also add a posting directly while discovery works in the background.' : 'Save, dismiss or mark jobs applied from your recommendations.'}</p></div> : <div className="space-y-4">{jobs.data?.items.map(job => <JobCard key={job.id} job={job} />)}</div>}
    <div className="flex items-center justify-between pb-6"><Button variant="outline" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 30))}>Previous</Button><span className="text-xs text-muted-foreground">Page {Math.floor(offset / 30) + 1}</span><Button variant="outline" disabled={jobs.data?.next_offset == null} onClick={() => setOffset(jobs.data?.next_offset ?? offset)}>Next</Button></div>
  </div>;
}
