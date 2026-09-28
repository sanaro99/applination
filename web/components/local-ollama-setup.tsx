"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Loader2, PlugZap } from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

type Worker = {
  id: string;
  created_at: string;
  last_seen_at: string | null;
  online: boolean;
  state: "pairing" | "pending" | "approved" | "expired";
  verification_code: string | null;
  expires_at: string | null;
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
  const [confirmation, setConfirmation] = useState<Record<string, string>>({});

  useEffect(() => onReadyChange?.(Boolean(data?.online)), [data?.online, onReadyChange]);
  useEffect(() => {
    if (!token) return;
    const timer = setTimeout(() => setToken(""), 5 * 60 * 1000);
    return () => clearTimeout(timer);
  }, [token]);

  async function create() {
    setBusy(true);
    setMessage("");
    try {
      const result = await request<{ token: string }>("/api/local-ollama/tokens", { method: "POST" });
      setToken(result.token);
      await refetch();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not create pairing code");
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

  async function approve(id: string) {
    setBusy(true);
    setMessage("");
    try {
      await request(`/api/local-ollama/tokens/${id}/approve`, {
        method: "POST", body: JSON.stringify({ verification_code: confirmation[id]?.trim() }),
      });
      setToken("");
      setConfirmation((current) => ({ ...current, [id]: "" }));
      await refetch();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not approve worker");
    } finally {
      setBusy(false);
    }
  }

  const body = (
    <div className="space-y-4 text-sm">
      <p>
        Applination can run its AI requests on your computer through Ollama.
        The official worker processes prompts locally. Run only the worker downloaded here and approve only a matching verification code.
      </p>
      <ol className="list-decimal space-y-2 pl-5 text-muted-foreground">
        <li>Install Ollama and run <code className="font-mono">ollama pull llama3.2</code>.</li>
        <li><a className="underline" href="/api/local-ollama/download" download>Download the Applination Ollama worker</a>. Python 3.10 or newer is required.</li>
        <li>Create a pairing code below, run <code className="font-mono">python applination-ollama-worker.py</code>, and paste it into the terminal. The code works once and expires in five minutes.</li>
        <li>Enter the verification code shown in that terminal below to approve the matching worker. Keep the worker open while using Ollama.</li>
        <li>Sessions expire after 12 hours, or one hour offline. Pair again afterward; scheduled runs need an active session.</li>
      </ol>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" size="sm" onClick={create} disabled={busy}>
          {busy && <Loader2 className="size-4 animate-spin" />}
          Create pairing code
        </Button>
        <a className={buttonVariants({ variant: "outline", size: "sm" })} href="https://ollama.com/download" target="_blank" rel="noopener noreferrer">Get Ollama</a>
        <span className={data?.online ? "text-emerald-600 dark:text-emerald-400" : "text-muted-foreground"}>
          {data?.online ? <><CheckCircle2 className="mr-1 inline size-4" /> Worker online</> : "Worker offline"}
        </span>
      </div>
      {token && (
        <div className="space-y-2 rounded-md border p-3">
          <p className="font-medium">Use this pairing code within five minutes. Never share it.</p>
          <code className="block break-all font-mono text-xs">{token}</code>
          <Button type="button" variant="outline" size="sm" onClick={() => void navigator.clipboard.writeText(token)}>Copy pairing code</Button>
        </div>
      )}
      {data?.workers.map((worker) => (
        <div key={worker.id} className="space-y-2 border-t pt-2 text-xs">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span>{worker.state === "pending" ? "Awaiting approval" : worker.state === "expired" ? "Expired — pair again" : worker.state === "pairing" ? "Waiting for worker" : worker.online ? "Online" : "Offline"} · Created {new Date(worker.created_at).toLocaleDateString()}</span>
            <Button type="button" size="sm" variant="ghost" onClick={() => void revoke(worker.id)}>Disconnect</Button>
          </div>
          {worker.state === "pending" && worker.verification_code && (
            <div className="space-y-2 rounded-md border p-3">
              <p>Worker verification code: <code className="font-mono font-semibold">{worker.verification_code}</code></p>
              <p>Approve only if this matches your terminal. Disconnect any unexpected worker.</p>
              <Input value={confirmation[worker.id] ?? ""} maxLength={12} autoComplete="off"
                aria-label="Verification code from worker terminal" placeholder="Code from your terminal"
                onChange={(event) => setConfirmation((current) => ({ ...current, [worker.id]: event.target.value }))} />
              <Button type="button" size="sm" onClick={() => void approve(worker.id)}
                disabled={busy || confirmation[worker.id]?.trim().toLowerCase() !== worker.verification_code}>
                Approve matching worker
              </Button>
            </div>
          )}
          {worker.expires_at && <p className="text-muted-foreground">Session expires {new Date(worker.expires_at).toLocaleString()}</p>}
        </div>
      ))}
      {message && <p role="alert" className="text-destructive">{message}</p>}
    </div>
  );

  if (compact) return <div className="rounded-md border bg-card/50 p-4">{body}</div>;
  return <Card><CardHeader><CardTitle className="flex items-center gap-2 text-base"><PlugZap className="size-4" /> Ollama on your computer</CardTitle></CardHeader><CardContent>{body}</CardContent></Card>;
}
