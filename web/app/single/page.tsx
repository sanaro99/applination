"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "motion/react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  ExternalLink,
  Loader2,
  Plus,
  Trash2,
  Sparkles,
} from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { ShineBorder } from "@/components/ui/shine-border";
import { LogTerminal, type LogLine } from "@/components/log-terminal";
import { api, fileUrl, subscribeRun } from "@/lib/api";
import type { PipelineEvent } from "@/lib/types";

type Step = "url" | "review" | "progress";

interface JobForm {
  company: string;
  title: string;
  location: string;
  remote: boolean;
  description: string;
  additional_questions: string[];
  specific_instructions: string;
  url: string;
}

const EMPTY: JobForm = {
  company: "",
  title: "",
  location: "",
  remote: false,
  description: "",
  additional_questions: [],
  specific_instructions: "",
  url: "",
};

export default function SingleJobPage() {
  const [step, setStep] = useState<Step>("url");
  const [form, setForm] = useState<JobForm>(EMPTY);
  const [runId, setRunId] = useState<number | null>(null);
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [done, setDone] = useState<{ folder_rel: string; error: string } | null>(
    null,
  );
  const [appId, setAppId] = useState<number | null>(null);
  const closeRef = useRef<null | (() => void)>(null);

  // After generation finishes, resolve the persisted application for this run so
  // we can deep-link straight to its in-app viewer (resume + cover + answers).
  useEffect(() => {
    if (!done || done.error || runId == null) return;
    let cancelled = false;
    api
      .listApplications({ run_id: runId })
      .then((apps) => {
        if (!cancelled && apps.length > 0) setAppId(apps[0].id);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [done, runId]);

  const extract = useMutation({
    mutationFn: (url: string) => api.extractJob(url),
    onSuccess: (data) => {
      setForm({
        company: data.company || "",
        title: data.title || "",
        location: data.location || "",
        remote: !!data.remote,
        description: data.description || "",
        additional_questions: data.additional_questions || [],
        specific_instructions: data.specific_instructions || "",
        url: data.url,
      });
      setStep("review");
    },
    onError: (e) => {
      toast.error(`Extract failed: ${String(e)}`);
      setStep("review");
    },
  });

  const generate = useMutation({
    mutationFn: (body: JobForm) => api.generateSingle(body),
    onSuccess: (data) => {
      setRunId(data.run_id);
      closeRef.current = subscribeRun(data.run_id, handleEvent, () => {
        toast.error("Lost connection to run stream");
      });
    },
    onError: (e) => {
      toast.error(`Generate failed: ${String(e)}`);
    },
  });

  useEffect(() => {
    return () => {
      if (closeRef.current) closeRef.current();
    };
  }, []);

  function handleEvent(evt: PipelineEvent) {
    if (evt.type === "log") {
      setLogs((l) => [
        ...l.slice(-499),
        { level: evt.level, msg: evt.msg, ts: Date.now() },
      ]);
    } else if (evt.type === "job_completed") {
      setDone({ folder_rel: evt.folder_rel, error: evt.error });
    } else if (evt.type === "error") {
      toast.error(evt.msg);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
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
            <Sparkles className="size-5 text-primary" /> Single application
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Stepper step={step} />
        </CardContent>
      </Card>

      <AnimatePresence mode="wait">
        {step === "url" && (
          <motion.div
            key="url"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.18 }}
          >
            <UrlStep
              loading={extract.isPending}
              onExtract={(url) => extract.mutate(url)}
              onSkip={() => {
                setForm({ ...EMPTY });
                setStep("review");
              }}
            />
          </motion.div>
        )}
        {step === "review" && (
          <motion.div
            key="review"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.18 }}
          >
            <ReviewStep
              form={form}
              setForm={setForm}
              onBack={() => setStep("url")}
              onSubmit={() => {
                generate.mutate(form);
                setStep("progress");
              }}
              submitting={generate.isPending}
            />
          </motion.div>
        )}
        {step === "progress" && (
          <motion.div
            key="progress"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.18 }}
          >
            <ProgressStep
              runId={runId}
              logs={logs}
              done={done}
              appId={appId}
              onRestart={() => {
                if (closeRef.current) closeRef.current();
                setRunId(null);
                setDone(null);
                setAppId(null);
                setLogs([]);
                setForm({ ...EMPTY });
                setStep("url");
              }}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function Stepper({ step }: { step: Step }) {
  const items: { id: Step; label: string }[] = [
    { id: "url", label: "1 · Job URL" },
    { id: "review", label: "2 · Review" },
    { id: "progress", label: "3 · Generate" },
  ];
  const activeIdx = items.findIndex((i) => i.id === step);
  return (
    <div className="flex items-center gap-2">
      {items.map((it, idx) => (
        <div key={it.id} className="flex flex-1 items-center gap-2">
          <Badge
            variant={idx <= activeIdx ? "default" : "outline"}
            className="whitespace-nowrap"
          >
            {it.label}
          </Badge>
          {idx < items.length - 1 && (
            <div className="h-px flex-1 bg-border" />
          )}
        </div>
      ))}
    </div>
  );
}

function UrlStep({
  loading,
  onExtract,
  onSkip,
}: {
  loading: boolean;
  onExtract: (url: string) => void;
  onSkip: () => void;
}) {
  const [url, setUrl] = useState("");
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Enter job URL</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label>Posting URL</Label>
          <Input
            placeholder="https://boards.greenhouse.io/company/jobs/12345"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            LinkedIn blocks automated browsers — paste those manually in the
            next step.
          </p>
        </div>
        <div className="flex justify-between">
          <Button variant="outline" onClick={onSkip}>
            Skip to manual
          </Button>
          <Button
            disabled={!url.trim() || loading}
            onClick={() => onExtract(url.trim())}
          >
            {loading ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <ArrowRight className="size-4" />
            )}
            Fetch & extract
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function ReviewStep({
  form,
  setForm,
  onBack,
  onSubmit,
  submitting,
}: {
  form: JobForm;
  setForm: (f: JobForm) => void;
  onBack: () => void;
  onSubmit: () => void;
  submitting: boolean;
}) {
  function patch<K extends keyof JobForm>(k: K, v: JobForm[K]) {
    setForm({ ...form, [k]: v });
  }

  const canSubmit = form.company.trim() && form.title.trim() && form.description.trim();

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Review & edit</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Company">
            <Input
              value={form.company}
              onChange={(e) => patch("company", e.target.value)}
            />
          </Field>
          <Field label="Title">
            <Input
              value={form.title}
              onChange={(e) => patch("title", e.target.value)}
            />
          </Field>
          <Field label="Location">
            <Input
              value={form.location}
              onChange={(e) => patch("location", e.target.value)}
            />
          </Field>
          <Field label="Remote">
            <div className="flex h-9 items-center">
              <Switch
                checked={form.remote}
                onCheckedChange={(v) => patch("remote", v)}
              />
            </div>
          </Field>
        </div>
        <Field label="Job description">
          <Textarea
            value={form.description}
            onChange={(e) => patch("description", e.target.value)}
            className="min-h-56"
          />
        </Field>
        <Field
          label="Additional questions"
          hint="Application essays / supplemental prompts — answers are auto-generated."
        >
          <div className="space-y-2">
            {form.additional_questions.map((q, i) => (
              <div key={i} className="flex gap-2">
                <Input
                  value={q}
                  onChange={(e) =>
                    patch(
                      "additional_questions",
                      form.additional_questions.map((x, j) =>
                        j === i ? e.target.value : x,
                      ),
                    )
                  }
                />
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() =>
                    patch(
                      "additional_questions",
                      form.additional_questions.filter((_, j) => j !== i),
                    )
                  }
                >
                  <Trash2 className="size-4" />
                </Button>
              </div>
            ))}
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                patch("additional_questions", [...form.additional_questions, ""])
              }
            >
              <Plus className="size-3" /> Add question
            </Button>
          </div>
        </Field>
        <Field label="Specific instructions">
          <Textarea
            value={form.specific_instructions}
            onChange={(e) => patch("specific_instructions", e.target.value)}
            placeholder="Word limits, portfolio requirements, custom submission steps…"
            className="min-h-20"
          />
        </Field>
        <div className="flex justify-between">
          <Button variant="outline" onClick={onBack}>
            <ArrowLeft className="size-4" /> Back
          </Button>
          <Button disabled={!canSubmit || submitting} onClick={onSubmit}>
            {submitting ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Sparkles className="size-4" />
            )}
            Generate
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function ProgressStep({
  runId,
  logs,
  done,
  appId,
  onRestart,
}: {
  runId: number | null;
  logs: LogLine[];
  done: { folder_rel: string; error: string } | null;
  appId: number | null;
  onRestart: () => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          {done ? (
            <>
              <CheckCircle2 className="size-4 text-emerald-500" /> Generated
            </>
          ) : (
            <>
              <Loader2 className="size-4 animate-spin" /> Generating…
            </>
          )}
          {runId && (
            <Badge variant="secondary" className="ml-2">
              Run #{runId}
            </Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <LogTerminal lines={logs} />
        {done && !done.error && (
          <div className="flex flex-wrap items-center gap-2">
            {["resume.docx", "resume.pdf", "cover_letter.docx", "cover_letter.pdf", "answers.md"].map((f) => (
              <a
                key={f}
                href={fileUrl(done.folder_rel, f)}
                className={buttonVariants({ variant: "outline", size: "sm" })}
                download
              >
                <ExternalLink className="size-3" /> {f}
              </a>
            ))}
          </div>
        )}
        {done && done.error && (
          <p className="text-sm text-destructive">
            Generation failed: {done.error}
          </p>
        )}
        <div className="flex justify-between">
          <Button variant="outline" onClick={onRestart}>
            Start over
          </Button>
          {done && !done.error && (
            <Link
              href={appId != null ? `/applications/${appId}` : "/applications"}
              className={buttonVariants()}
            >
              {appId != null ? "View application" : "See applications"}
            </Link>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label className="text-sm">{label}</Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}
