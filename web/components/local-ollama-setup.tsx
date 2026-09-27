"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Loader2, PlugZap } from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type Worker = {
  id: string;
  created_at: string;
  last_seen_at: string | null;
  online: boolean;
};
type Status = { online: boolean; workers: Worker[] };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

export function LocalOllamaSetup({ compact = false, onReadyChange }: {
  compact?: boolean;
  onReadyChange?: (ready: boolean) => void;
}) {
  const { data, refetch } = useQuery({
    queryKey: ["local-ollama-status"],
    queryFn: () => request<Status>("/api/local-ollama/status"),
    refetchInterval: 5000,
  });
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => onReadyChange?.(Boolean(data?.online)), [data?.online, onReadyChange]);

  async function create() {
    setBusy(true);
    setMessage("");
    try {
      const result = await request<{ token: string }>("/api/local-ollama/tokens", { method: "POST" });
      setToken(result.token);
      await refetch();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not create connection key");
    } finally {
      setBusy(false);
    }
  }

  async function revoke(id: string) {
    try {
      await request(`/api/local-ollama/tokens/${id}`, { method: "DELETE" });
      setToken("");
      await refetch();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not disconnect worker");
    }
  }

  const body = (
    <div className="space-y-4 text-sm">
      <p>
        Applination can run its AI requests on your computer through Ollama.
        AI companies cannot use the prompts processed by this local connection.
      </p>
      <ol className="list-decimal space-y-2 pl-5 text-muted-foreground">
        <li>Install Ollama and run <code className="font-mono">ollama pull llama3.2</code>.</li>
        <li><a className="underline" href="/api/local-ollama/download" download>Download the Applination Ollama worker</a>. Python 3.10 or newer is required.</li>
        <li>Create a connection key below, then run <code className="font-mono">python applination-ollama-worker.py</code> from the download folder and paste the key when prompted.</li>
        <li>Keep the worker running while you use the website or extension. Scheduled runs also need it running.</li>
      </ol>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" size="sm" onClick={create} disabled={busy}>
          {busy && <Loader2 className="size-4 animate-spin" />}
          Create connection key
        </Button>
        <a className={buttonVariants({ variant: "outline", size: "sm" })} href="https://ollama.com/download" target="_blank" rel="noopener noreferrer">Get Ollama</a>
        <span className={data?.online ? "text-emerald-600 dark:text-emerald-400" : "text-muted-foreground"}>
          {data?.online ? <><CheckCircle2 className="mr-1 inline size-4" /> Worker online</> : "Worker offline"}
        </span>
      </div>
      {token && (
        <div className="space-y-2 rounded-md border p-3">
          <p className="font-medium">Copy this key now. It will only be shown once.</p>
          <code className="block break-all font-mono text-xs">{token}</code>
          <Button type="button" variant="outline" size="sm" onClick={() => void navigator.clipboard.writeText(token)}>Copy key</Button>
        </div>
      )}
      {data?.workers.map((worker) => (
        <div key={worker.id} className="flex flex-wrap items-center justify-between gap-2 border-t pt-2 text-xs">
          <span>{worker.online ? "Online" : "Offline"} · Connected {new Date(worker.created_at).toLocaleDateString()}</span>
          <Button type="button" size="sm" variant="ghost" onClick={() => void revoke(worker.id)}>Disconnect</Button>
        </div>
      ))}
      {message && <p role="alert" className="text-destructive">{message}</p>}
    </div>
  );

  if (compact) return <div className="rounded-md border bg-card/50 p-4">{body}</div>;
  return <Card><CardHeader><CardTitle className="flex items-center gap-2 text-base"><PlugZap className="size-4" /> Ollama on your computer</CardTitle></CardHeader><CardContent>{body}</CardContent></Card>;
}
