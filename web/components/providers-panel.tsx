"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2, Settings2, XCircle, Zap } from "lucide-react";
import { toast } from "sonner";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import type { ProviderInfo, ProviderTestResult } from "@/lib/types";
import { cn } from "@/lib/utils";

export function ProvidersPanel() {
  const { data: providers, isLoading } = useQuery({
    queryKey: ["providers"],
    queryFn: () => api.listProviders(),
  });
  const [results, setResults] = useState<Record<string, ProviderTestResult>>({});
  const [testing, setTesting] = useState<string | null>(null);
  const [editing, setEditing] = useState<ProviderInfo | null>(null);

  const test = useMutation({
    mutationFn: (provider: string) => api.testProvider(provider),
    onMutate: (provider) => setTesting(provider),
    onSuccess: (r) => setResults((prev) => ({ ...prev, [r.provider]: r })),
    onError: (error, provider) => setResults((prev) => ({
      ...prev,
      [provider]: {
        ok: false, provider, model: "", latency_ms: 0, sample: "", error: error.message,
      },
    })),
    onSettled: () => setTesting(null),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Zap className="size-4 text-primary" /> LLM providers
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {isLoading ? (
          <Skeleton className="h-32 w-full" />
        ) : (providers ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No providers found in config.yaml.
          </p>
        ) : (
          (providers ?? []).map((p) => {
            const r = results[p.name];
            return (
              <div
                key={p.name}
                className="flex flex-wrap items-center gap-3 rounded-md border border-border/60 p-3"
              >
                <div className="flex min-w-0 basis-full flex-wrap items-center gap-2 sm:flex-1 sm:basis-0 sm:flex-nowrap">
                  <span className="font-medium capitalize">{p.name}</span>
                  {p.role !== "available" && (
                    <Badge variant="outline" className="text-xs capitalize">
                      {p.role}
                    </Badge>
                  )}
                  {p.model && (
                    <span className="order-last w-full truncate font-mono text-xs text-muted-foreground sm:order-none sm:w-auto">
                      {p.model}
                    </span>
                  )}
                  {!p.configured && (
                    <Badge variant="outline" className="text-xs text-amber-600 dark:text-amber-400">
                      {p.name === "ollama" ? "worker offline" : "no api key"}
                    </Badge>
                  )}
                </div>
                {r && (
                  <span
                    className={cn(
                      "flex min-w-0 max-w-full items-center gap-1 text-xs",
                      r.ok
                        ? "text-emerald-600 dark:text-emerald-400"
                        : "text-red-600 dark:text-red-400",
                    )}
                  >
                    {r.ok ? (
                      <>
                        <CheckCircle2 className="size-3.5" /> ok · {r.latency_ms}ms
                      </>
                    ) : (
                      <>
                        <XCircle className="size-3.5" />
                        <span className="max-w-60 truncate" title={r.error}>
                          {r.error || "failed"}
                        </span>
                      </>
                    )}
                  </span>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => test.mutate(p.name)}
                  disabled={testing === p.name}
                >
                  {testing === p.name ? (
                    <Loader2 className="size-3.5 animate-spin" />
                  ) : null}
                  Test
                </Button>
                <Button size="sm" variant="outline" onClick={() => setEditing(p)}>
                  <Settings2 className="size-3.5" /> Configure
                </Button>
              </div>
            );
          })
        )}
        <p className="pt-1 text-xs text-muted-foreground">
          A test makes one short model call to check connectivity and latency.
        </p>
      </CardContent>
      <Dialog open={editing !== null} onOpenChange={(open) => { if (!open) setEditing(null); }}>
        {editing && (
          <DialogContent className="sm:max-w-lg">
            <ProviderConfiguration
              key={editing.name}
              provider={editing}
              onSaved={() => {
                setResults((prev) => {
                  const next = { ...prev };
                  delete next[editing.name];
                  return next;
                });
                setEditing(null);
              }}
            />
          </DialogContent>
        )}
      </Dialog>
    </Card>
  );
}

function ProviderConfiguration({ provider, onSaved }: {
  provider: ProviderInfo;
  onSaved: () => void;
}) {
  const qc = useQueryClient();
  const [model, setModel] = useState(provider.model);
  const [apiKey, setApiKey] = useState("");
  const [accountId, setAccountId] = useState(provider.account_id || "");
  const [models, setModels] = useState<string[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [catalog, setCatalog] = useState(false);
  const [manual, setManual] = useState(false);
  const isOllama = provider.name === "ollama";
  const isCloudflare = provider.name === "cloudflare";

  const discover = useMutation({
    mutationFn: (browseCatalog: boolean) => api.listProviderModels(provider.name, {
      catalog: !isOllama && browseCatalog,
      api_key: browseCatalog ? undefined : apiKey.trim() || undefined,
      account_id: isCloudflare && !browseCatalog ? accountId.trim() : undefined,
    }),
    onSuccess: ({ models, source }) => {
      setModels(models);
      setLoaded(true);
      setCatalog(source === "catalog");
    },
  });
  const save = useMutation({
    mutationFn: () => api.configureProvider(provider.name, {
      model: model.trim(),
      api_key: apiKey.trim() || undefined,
      account_id: isCloudflare ? accountId.trim() : undefined,
    }),
    onSuccess: () => {
      void Promise.all([
        qc.invalidateQueries({ queryKey: ["providers"] }),
        qc.invalidateQueries({ queryKey: ["llm-config"] }),
        qc.invalidateQueries({ queryKey: ["secrets"] }),
        qc.invalidateQueries({ queryKey: ["config"] }),
      ]);
      toast.success(`${provider.name} configuration saved`);
      onSaved();
    },
  });
  const options = model && !models.includes(model) ? [model, ...models] : models;

  return (
    <>
      <DialogHeader>
        <DialogTitle className="capitalize">Configure {provider.name}</DialogTitle>
        <DialogDescription>
          {isOllama
            ? "Choose the local model used for Ollama."
            : "Choose the model used for this provider. A new key replaces the stored key; leave it blank to keep the current one."}
        </DialogDescription>
      </DialogHeader>
      <div className="space-y-4">
        {!isOllama && (
          <div className="space-y-1.5">
            <Label htmlFor="provider-api-key">{isCloudflare ? "API token" : "API key"}</Label>
            <Input
              id="provider-api-key"
              type="password"
              autoComplete="off"
              value={apiKey}
              onChange={(e) => {
                setApiKey(e.target.value);
                if (!catalog) {
                  setLoaded(false);
                  setModels([]);
                }
              }}
              placeholder={provider.configured ? "Stored key (enter a new one to replace it)" : "Paste your key"}
            />
          </div>
        )}
        {isCloudflare && (
          <div className="space-y-1.5">
            <Label htmlFor="provider-account-id">Account ID</Label>
            <Input
              id="provider-account-id"
              value={accountId}
              onChange={(e) => {
                setAccountId(e.target.value);
                if (!catalog) {
                  setLoaded(false);
                  setModels([]);
                }
              }}
              placeholder="Cloudflare account ID"
            />
          </div>
        )}
        <div className="space-y-1.5">
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={discover.isPending}
            onClick={() => discover.mutate(true)}
          >
            {discover.isPending && <Loader2 className="size-3.5 animate-spin" />}
            Load available models
          </Button>
          {!isOllama && (apiKey.trim() || provider.configured) && (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={discover.isPending || (isCloudflare && !accountId.trim())}
              onClick={() => discover.mutate(false)}
            >
              Load models for my key
            </Button>
          )}
          {discover.isError && <p className="text-xs text-destructive">{String(discover.error)}</p>}
          {loaded && models.length === 0 && (
            <p className="text-xs text-muted-foreground">This provider returned no model IDs. Enter the model ID below.</p>
          )}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="provider-model">Model ID</Label>
          {models.length > 0 && !manual ? (
            <select
              id="provider-model"
              className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={model}
              onChange={(e) => setModel(e.target.value)}
            >
              {!model && <option value="">Select a model</option>}
              {options.map((id) => <option key={id} value={id}>{id}</option>)}
            </select>
          ) : (
            <Input
              id="provider-model"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="Enter the exact provider model ID"
            />
          )}
          {models.length > 0 && (
            <button
              type="button"
              className="text-xs text-primary underline-offset-4 hover:underline"
              onClick={() => setManual((value) => !value)}
            >
              {manual ? "Choose from the list" : "Enter a different model ID"}
            </button>
          )}
          <p className="text-xs text-muted-foreground">
            {isOllama
              ? "Lists installed Ollama models. If you use Ollama on your computer, keep the local worker running."
              : catalog
                ? "Public model catalog from Models.dev. Add a key and test your selection after saving to confirm access."
                : "Browse models without a key, or load the list for your key. Test your selection after saving to confirm it supports this app’s requests."}
          </p>
        </div>
      </div>
      {save.isError && <p className="text-xs text-destructive">{String(save.error)}</p>}
      <DialogFooter>
        <Button
          disabled={save.isPending || !model.trim() || (isCloudflare && !accountId.trim())}
          onClick={() => save.mutate()}
        >
          {save.isPending && <Loader2 className="size-3.5 animate-spin" />}
          Save configuration
        </Button>
      </DialogFooter>
    </>
  );
}
