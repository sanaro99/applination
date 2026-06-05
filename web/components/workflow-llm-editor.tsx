"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2, Save } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api";
import type { LlmConfig } from "@/lib/types";
import { cn } from "@/lib/utils";

// Friendly labels + grouping for each task key the backend exposes.
const TASK_META: Record<string, { label: string; group: string; hint: string }> = {
  ranking: { label: "Job ranking", group: "Pipeline", hint: "Scores job batches" },
  tailoring: { label: "Resume tailoring", group: "Pipeline", hint: "Standard resumes" },
  tailoring_premium: { label: "Resume tailoring · premium", group: "Pipeline", hint: "Top-N jobs" },
  cover_letter: { label: "Cover letters", group: "Pipeline", hint: "Letter writing" },
  critique: { label: "Critique", group: "Pipeline", hint: "Quality scoring" },
  answer_questions: { label: "Application Q&A", group: "Pipeline", hint: "Short answers" },
  coach: { label: "Coach chat", group: "Prepwork & editing", hint: "Profile chat" },
  interview: { label: "Mock interview", group: "Prepwork & editing", hint: "Interview coach" },
  essay: { label: "Essay drafter", group: "Prepwork & editing", hint: "Scholarship / essays" },
  content_studio: { label: "Content studio", group: "Prepwork & editing", hint: "Story / bio edits" },
};
const GROUPS = ["Pipeline", "Prepwork & editing"];

// Curated model suggestions per provider (a free-text field covers the rest).
const CURATED_MODELS: Record<string, string[]> = {
  deepseek: ["deepseek-chat", "deepseek-reasoner", "deepseek-v4-pro"],
  mistral: ["mistral-small-latest", "mistral-medium-latest", "open-mixtral-8x22b"],
  gemini: ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.5-pro"],
  claude: ["claude-haiku-4-5-20251001", "claude-sonnet-4-6", "claude-opus-4-8"],
  openrouter: ["tencent/hunyuan-a13b-instruct:free"],
  nim: ["meta/llama-3.1-8b-instruct", "meta/llama-3.1-70b-instruct"],
  ollama: ["llama3.2", "qwen2.5"],
};

interface TaskState {
  inherit: boolean;
  primary: string;
  fallbacks: string[];
  model: string; // model override for the primary provider
}

function buildState(cfg: LlmConfig) {
  const globalPrimary = cfg.global.primary ?? "";
  const tasks: Record<string, TaskState> = {};
  for (const name of cfg.task_names) {
    const t = cfg.tasks[name];
    if (t) {
      const primary = t.primary ?? globalPrimary;
      tasks[name] = {
        inherit: false,
        primary,
        fallbacks: t.fallbacks ?? [],
        model: t.models?.[primary] ?? "",
      };
    } else {
      tasks[name] = {
        inherit: true,
        primary: globalPrimary,
        fallbacks: cfg.global.fallbacks,
        model: "",
      };
    }
  }
  return {
    primary: globalPrimary,
    fallbacks: cfg.global.fallbacks,
    tasks,
  };
}

export function WorkflowLlmEditor() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["llm-config"],
    queryFn: () => api.getLlmConfig(),
  });

  if (isLoading || !data) return <Skeleton className="h-[60svh] w-full" />;
  return <Editor key={JSON.stringify(data.tasks)} cfg={data} qc={qc} />;
}

function Editor({
  cfg,
  qc,
}: {
  cfg: LlmConfig;
  qc: ReturnType<typeof useQueryClient>;
}) {
  const providers = cfg.providers.map((p) => p.name);
  const [state, setState] = useState(() => buildState(cfg));

  const save = useMutation({
    mutationFn: () => {
      const tasks: Record<
        string,
        { primary: string; fallbacks: string[]; models: Record<string, string> }
      > = {};
      for (const [name, t] of Object.entries(state.tasks)) {
        if (t.inherit) continue;
        tasks[name] = {
          primary: t.primary,
          fallbacks: t.fallbacks,
          models: t.model ? { [t.primary]: t.model } : {},
        };
      }
      return api.putLlmConfig({
        global: { primary: state.primary, fallbacks: state.fallbacks },
        tasks,
      });
    },
    onSuccess: () => {
      toast.success("LLM routing saved");
      qc.invalidateQueries({ queryKey: ["llm-config"] });
      qc.invalidateQueries({ queryKey: ["providers"] });
    },
    onError: (e) => toast.error(String(e)),
  });

  function updateTask(name: string, patch: Partial<TaskState>) {
    setState((s) => ({
      ...s,
      tasks: { ...s.tasks, [name]: { ...s.tasks[name], ...patch } },
    }));
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Choose the model for each workflow. Tasks set to inherit use the
          global default below.
        </p>
        <Button onClick={() => save.mutate()} disabled={save.isPending} className="gap-2">
          {save.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Save className="size-4" />
          )}
          Save
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Global default</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Row label="Primary provider">
            <ProviderDropdown
              providers={providers}
              value={state.primary}
              onChange={(v) => setState((s) => ({ ...s, primary: v }))}
            />
          </Row>
          <Row label="Fallbacks">
            <FallbackChips
              providers={providers}
              primary={state.primary}
              value={state.fallbacks}
              onChange={(fb) => setState((s) => ({ ...s, fallbacks: fb }))}
            />
          </Row>
        </CardContent>
      </Card>

      {GROUPS.map((group) => (
        <Card key={group}>
          <CardHeader>
            <CardTitle className="text-base">{group}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {cfg.task_names
              .filter((n) => TASK_META[n]?.group === group)
              .map((name) => (
                <TaskCard
                  key={name}
                  name={name}
                  providers={providers}
                  state={state.tasks[name]}
                  onChange={(patch) => updateTask(name, patch)}
                />
              ))}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function TaskCard({
  name,
  providers,
  state,
  onChange,
}: {
  name: string;
  providers: string[];
  state: TaskState;
  onChange: (patch: Partial<TaskState>) => void;
}) {
  const meta = TASK_META[name] ?? { label: name, hint: "" };
  return (
    <div className="rounded-xl border border-border p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">{meta.label}</span>
            <code className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
              {name}
            </code>
          </div>
          <p className="text-xs text-muted-foreground">{meta.hint}</p>
        </div>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          Inherit global
          <Switch
            checked={state.inherit}
            onCheckedChange={(c) => onChange({ inherit: c })}
          />
        </label>
      </div>

      {!state.inherit && (
        <div className="mt-3 space-y-3 border-t border-border/60 pt-3">
          <Row label="Provider">
            <ProviderDropdown
              providers={providers}
              value={state.primary}
              onChange={(v) => onChange({ primary: v, model: "" })}
            />
          </Row>
          <Row label="Model">
            <ModelCombo
              provider={state.primary}
              value={state.model}
              onChange={(v) => onChange({ model: v })}
            />
          </Row>
          <Row label="Fallbacks">
            <FallbackChips
              providers={providers}
              primary={state.primary}
              value={state.fallbacks}
              onChange={(fb) => onChange({ fallbacks: fb })}
            />
          </Row>
        </div>
      )}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center">
      <Label className="w-32 shrink-0 text-xs text-muted-foreground">
        {label}
      </Label>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

function ProviderDropdown({
  providers,
  value,
  onChange,
}: {
  providers: string[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <Select value={value} onValueChange={(v) => v && onChange(v)}>
      <SelectTrigger className="w-56">
        <SelectValue placeholder="Provider…" />
      </SelectTrigger>
      <SelectContent>
        {providers.map((p) => (
          <SelectItem key={p} value={p}>
            {p}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function ModelCombo({
  provider,
  value,
  onChange,
}: {
  provider: string;
  value: string;
  onChange: (v: string) => void;
}) {
  const curated = CURATED_MODELS[provider] ?? [];
  return (
    <div className="flex flex-wrap items-center gap-2">
      {curated.length > 0 && (
        <Select value="" onValueChange={(v) => v && onChange(v)}>
          <SelectTrigger className="w-44 text-xs">
            <SelectValue placeholder="Quick pick…" />
          </SelectTrigger>
          <SelectContent>
            {curated.map((m) => (
              <SelectItem key={m} value={m}>
                {m}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="provider default"
        className="w-64 font-mono text-xs"
      />
    </div>
  );
}

function FallbackChips({
  providers,
  primary,
  value,
  onChange,
}: {
  providers: string[];
  primary: string;
  value: string[];
  onChange: (fallbacks: string[]) => void;
}) {
  const toggle = (p: string) => {
    if (value.includes(p)) onChange(value.filter((x) => x !== p));
    else onChange([...value, p]); // preserve click order
  };
  return (
    <div className="flex flex-wrap gap-1.5">
      {providers
        .filter((p) => p !== primary)
        .map((p) => {
          const active = value.includes(p);
          const order = value.indexOf(p);
          return (
            <button
              key={p}
              type="button"
              onClick={() => toggle(p)}
              className={cn(
                "rounded-full border px-2.5 py-1 text-xs transition-colors",
                active
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border text-muted-foreground hover:bg-muted",
              )}
            >
              {active && (
                <Badge
                  variant="secondary"
                  className="mr-1 h-4 px-1 text-[9px] tabular-nums"
                >
                  {order + 1}
                </Badge>
              )}
              {p}
            </button>
          );
        })}
    </div>
  );
}
