"use client";

import { use, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { toast } from "sonner";
import {
  ArrowLeft,
  Download,
  ExternalLink,
  FileText,
  Briefcase,
  Mail,
} from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { api, downloadUrl, fileUrl } from "@/lib/api";
import type { ApplicationStatus } from "@/lib/types";
import { ScoreChip, STATUSES, StatusBadge } from "@/components/status-badge";
import { TweakPanel } from "@/components/tweak-panel";
import { CoverLetterTab } from "@/components/cover-letter-tab";

export default function ApplicationDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const appId = Number(id);
  const qc = useQueryClient();

  const { data: app, isLoading } = useQuery({
    queryKey: ["application", appId],
    queryFn: () => api.getApplication(appId),
  });

  // Shares the cache key with TweakPanel; a tweak invalidates it there, which
  // refetches here so the preview swaps to the freshly generated version.
  const { data: versions } = useQuery({
    queryKey: ["resume-versions", appId],
    queryFn: () => api.listResumeVersions(appId),
  });

  const update = useMutation({
    mutationFn: (
      body: Partial<{
        status: ApplicationStatus;
        notes: string;
        tags: string[];
        applied_at: string | null;
        deadline: string | null;
      }>,
    ) =>
      api.patchApplication(appId, body as never),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["application", appId] });
      qc.invalidateQueries({ queryKey: ["applications"] });
    },
    onError: (e) => toast.error(String(e)),
  });

  const [notes, setNotes] = useState("");
  useEffect(() => {
    if (app && app.notes !== notes) setNotes(app.notes);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [app?.id]);

  useEffect(() => {
    if (!app) return;
    if (notes === app.notes) return;
    const t = setTimeout(() => update.mutate({ notes }), 700);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notes]);

  // Preview the latest version that has a rendered PDF (the freshest tweak), so
  // the iframe reflects edits made via the Tweak panel. Falls back to the base.
  const latestResume = useMemo(() => {
    const withPdf = (versions?.versions ?? []).filter((v) => v.pdf);
    if (withPdf.length === 0) return null;
    return withPdf[withPdf.length - 1]; // list is sorted ascending by version
  }, [versions]);

  const resumePdfUrl = useMemo(() => {
    if (!app) return "";
    return fileUrl(app.folder_rel, latestResume?.pdf ?? "resume.pdf");
  }, [app, latestResume]);
  const coverPdfUrl = useMemo(() => {
    if (!app) return "";
    return fileUrl(app.folder_rel, "cover_letter.pdf");
  }, [app]);

  if (isLoading || !app) {
    return <Skeleton className="h-[80svh]" />;
  }

  return (
    <div className="mx-auto max-w-[1440px] space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link
          href="/applications"
          className={buttonVariants({ variant: "ghost", size: "sm" })}
        >
          <ArrowLeft className="size-4" /> Applications
        </Link>
        <div className="flex flex-wrap items-center gap-2">
          {app.url && (
            <a
              href={app.url}
              target="_blank"
              rel="noreferrer"
              className={buttonVariants({ variant: "outline", size: "sm" })}
            >
              <ExternalLink className="size-3" /> Job posting
            </a>
          )}
          <DownloadLinks appId={appId} hasCover={!!app.cover_file} />
        </div>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4">
          <div className="space-y-1">
            <CardTitle className="text-gradient text-2xl font-bold">
              {app.company}
            </CardTitle>
            <p className="text-muted-foreground">{app.title}</p>
            <p className="text-sm text-muted-foreground">
              {app.location || "Location not specified"}
              {app.source && ` · ${app.source}`}
            </p>
            {app.match_reason && (
              <p className="max-w-2xl pt-2 text-sm text-muted-foreground">
                {app.match_reason}
              </p>
            )}
          </div>
          <div className="flex flex-col items-end gap-2">
            <ScoreChip score={app.match_score} />
            <StatusBadge status={app.status} />
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <StatusControl
              status={app.status}
              onChange={(v) => update.mutate({ status: v })}
            />
            <AppliedDateControl
              label="Applied on"
              value={app.applied_at}
              onChange={(v) =>
                update.mutate({ applied_at: v ? new Date(v).toISOString() : null })
              }
            />
            <AppliedDateControl
              label="Deadline"
              value={app.deadline}
              onChange={(v) =>
                update.mutate({ deadline: v ? new Date(v).toISOString() : null })
              }
            />
            <div>
              <Label className="mb-1.5 block text-xs uppercase tracking-wide text-muted-foreground">
                Run
              </Label>
              {app.run_id != null ? (
                <Link
                  href={`/runs/${app.run_id}`}
                  className="text-sm hover:underline"
                >
                  Run #{app.run_id}
                </Link>
              ) : (
                <Badge variant="outline">Manual</Badge>
              )}
            </div>
          </div>
          <div className="mt-4">
            <TagsControl
              tags={app.tags}
              onChange={(tags) => update.mutate({ tags })}
            />
          </div>
        </CardContent>
      </Card>

      <div className="grid items-start gap-5 xl:grid-cols-2">
        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle className="flex items-center justify-between gap-2 text-base">
              <span className="flex items-center gap-2">
                <FileText className="size-4 text-primary" /> Resume
              </span>
              {latestResume && latestResume.version > 1 && (
                <Badge variant="secondary" className="font-mono">
                  Showing v{latestResume.version}
                </Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {resumePdfUrl ? (
              <iframe
                key={resumePdfUrl}
                src={resumePdfUrl}
                className="h-[78svh] w-full rounded-lg border border-border bg-muted"
                title="resume.pdf"
              />
            ) : (
              <p className="text-sm text-muted-foreground">
                No resume.pdf for this application.
              </p>
            )}
          </CardContent>
        </Card>
        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Mail className="size-4 text-primary" /> Cover letter
            </CardTitle>
          </CardHeader>
          <CardContent>
            <CoverLetterTab appId={appId} coverPdfUrl={coverPdfUrl} />
          </CardContent>
        </Card>
      </div>

      <div className="grid items-start gap-5 lg:grid-cols-[1.7fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Briefcase className="size-4 text-primary" /> Materials
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Tabs defaultValue="answers">
              <TabsList>
                <TabsTrigger value="answers">Answers</TabsTrigger>
                <TabsTrigger value="job">Job JSON</TabsTrigger>
                <TabsTrigger value="resume">Resume JSON</TabsTrigger>
              </TabsList>
              <TabsContent value="answers" className="mt-3">
                <FileViewer
                  url={fileUrl(app.folder_rel, "answers.md")}
                  empty="No additional-question answers for this application."
                  prose
                />
              </TabsContent>
              <TabsContent value="job" className="mt-3">
                <FileViewer
                  url={fileUrl(app.folder_rel, "job.json")}
                  empty="No job.json."
                />
              </TabsContent>
              <TabsContent value="resume" className="mt-3">
                <FileViewer
                  url={fileUrl(app.folder_rel, "resume.json")}
                  empty="No resume.json."
                />
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>
        <div className="flex flex-col gap-5">
          <TweakPanel appId={appId} folderRel={app.folder_rel} />
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Notes</CardTitle>
            </CardHeader>
            <CardContent>
              <Textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Personal notes, status updates, follow-ups…"
                className="min-h-40"
              />
              <p className="mt-1 text-xs text-muted-foreground">
                Auto-saves shortly after you stop typing.
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

function DownloadLinks({
  appId,
  hasCover,
}: {
  appId: number;
  hasCover: boolean;
}) {
  // Names are set server-side via Content-Disposition (e.g.
  // Sanchit_Arora_resume_Cloudflare.pdf), so the saved file is ATS-ready.
  const links: { label: string; doc: "resume" | "cover"; fmt: "pdf" | "docx" }[] = [
    { label: "Resume PDF", doc: "resume", fmt: "pdf" },
    { label: "Resume DOCX", doc: "resume", fmt: "docx" },
    ...(hasCover
      ? ([
          { label: "Cover PDF", doc: "cover", fmt: "pdf" },
          { label: "Cover DOCX", doc: "cover", fmt: "docx" },
        ] as const)
      : []),
  ];
  return (
    <div className="flex flex-wrap gap-1">
      {links.map((l) => (
        <a
          key={l.label}
          href={downloadUrl(appId, l.doc, l.fmt)}
          className={buttonVariants({ variant: "outline", size: "sm" })}
          download
        >
          <Download className="size-3" /> {l.label}
        </a>
      ))}
    </div>
  );
}

function StatusControl({
  status,
  onChange,
}: {
  status: ApplicationStatus;
  onChange: (v: ApplicationStatus) => void;
}) {
  return (
    <div>
      <Label className="mb-1.5 block text-xs uppercase tracking-wide text-muted-foreground">
        Status
      </Label>
      <Select value={status} onValueChange={(v) => onChange(v as ApplicationStatus)}>
        <SelectTrigger>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {STATUSES.map((s) => (
            <SelectItem key={s} value={s} className="capitalize">
              {s}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function AppliedDateControl({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string | null;
  onChange: (v: string | null) => void;
}) {
  const ymd = value ? new Date(value).toISOString().slice(0, 10) : "";
  return (
    <div>
      <Label className="mb-1.5 block text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </Label>
      <Input
        type="date"
        value={ymd}
        onChange={(e) => onChange(e.target.value || null)}
      />
    </div>
  );
}

function TagsControl({
  tags,
  onChange,
}: {
  tags: string[];
  onChange: (tags: string[]) => void;
}) {
  const [draft, setDraft] = useState("");

  function commit() {
    const t = draft.trim().replace(/,$/, "").trim();
    if (t && !tags.includes(t)) onChange([...tags, t]);
    setDraft("");
  }

  return (
    <div>
      <Label className="mb-1.5 block text-xs uppercase tracking-wide text-muted-foreground">
        Tags
      </Label>
      <div className="flex flex-wrap items-center gap-1.5">
        {tags.map((t) => (
          <Badge key={t} variant="secondary" className="gap-1">
            {t}
            <button
              type="button"
              onClick={() => onChange(tags.filter((x) => x !== t))}
              aria-label={`Remove ${t}`}
              className="text-muted-foreground hover:text-foreground"
            >
              ×
            </button>
          </Badge>
        ))}
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              commit();
            }
          }}
          onBlur={commit}
          placeholder="Add tag…"
          className="h-7 w-32 border-dashed"
        />
      </div>
    </div>
  );
}

function FileViewer({
  url,
  empty,
  prose = false,
}: {
  url: string;
  empty: string;
  prose?: boolean;
}) {
  const [text, setText] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setText(null);
    setErr(null);
    if (!url) {
      setErr(empty);
      return;
    }
    fetch(url)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status}`);
        return r.text();
      })
      .then((t) => {
        if (!cancelled) setText(t);
      })
      .catch(() => {
        if (!cancelled) setErr(empty);
      });
    return () => {
      cancelled = true;
    };
  }, [url, empty]);

  if (err) return <p className="text-sm text-muted-foreground">{err}</p>;
  if (text == null) return <Skeleton className="h-40 w-full" />;
  if (prose) {
    return (
      <div className="max-h-[60svh] overflow-auto whitespace-pre-wrap rounded-md border border-border bg-muted/40 p-4 text-sm leading-relaxed">
        {text}
      </div>
    );
  }
  return (
    <pre className="max-h-[60svh] overflow-auto rounded-md border border-border bg-muted/40 p-3 text-xs">
      {text}
    </pre>
  );
}
