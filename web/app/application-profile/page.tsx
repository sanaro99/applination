"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, ContactRound, FileText, Plus, Trash2 } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

const fields = [
  ["address", "Street address"], ["city", "City"], ["state", "State or province"],
  ["postal_code", "Postal code"], ["country", "Country"], ["website", "Other website"],
  ["work_authorization", "Work authorization"], ["sponsorship", "Sponsorship"],
  ["relocation", "Willing to relocate"], ["salary", "Salary expectation"],
  ["availability", "Availability"], ["preferred_name", "Preferred name"],
  ["pronouns", "Pronouns"], ["veteran", "Veteran status (optional)"],
  ["disability", "Disability status (optional)"], ["gender", "Gender (optional)"],
  ["ethnicity", "Ethnicity (optional)"],
] as const;

type Profile = { account: string; contact: Record<string, string>; extra: Record<string, string> };
type Answer = { id: number; prompt: string; content: string };

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init, credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data as T;
}

export default function ApplicationProfilePage() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [extra, setExtra] = useState<Record<string, string>>({});
  const [answers, setAnswers] = useState<Answer[]>([]);
  const [prompt, setPrompt] = useState("");
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all([
      json<Profile>("/api/application-profile"),
      json<Answer[]>("/api/application-profile/answers"),
    ]).then(([data, saved]) => {
      if (!active) return;
      setProfile(data);
      setExtra(data.extra || {});
      setAnswers(saved);
    }).catch((error) => { if (active) setMessage(error.message); });
    return () => { active = false; };
  }, []);

  async function saveProfile() {
    setBusy(true);
    setMessage("");
    try {
      await json("/api/application-profile", { method: "PUT", body: JSON.stringify({ extra }) });
      setMessage("Application profile saved.");
    } catch (error) { setMessage(String(error)); }
    finally { setBusy(false); }
  }

  async function addAnswer() {
    setBusy(true);
    setMessage("");
    try {
      await json("/api/application-profile/answers", {
        method: "POST", body: JSON.stringify({ prompt: prompt.trim(), content: content.trim() }),
      });
      setAnswers(await json<Answer[]>("/api/application-profile/answers"));
      setPrompt("");
      setContent("");
      setMessage("Answer saved for future applications.");
    } catch (error) { setMessage(String(error)); }
    finally { setBusy(false); }
  }

  async function removeAnswer(id: number) {
    setBusy(true);
    setMessage("");
    try {
      await json(`/api/application-profile/answers/${id}`, { method: "DELETE" });
      setAnswers((current) => current.filter((answer) => answer.id !== id));
    } catch (error) { setMessage(String(error)); }
    finally { setBusy(false); }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <div className="relative overflow-hidden rounded-2xl border border-border bg-card p-6">
        <div className="pointer-events-none absolute -right-16 -top-24 size-64 rounded-full bg-primary/10 blur-3xl" />
        <div className="relative space-y-2">
          <span className="inline-flex items-center gap-2 rounded-full border border-border bg-background/70 px-3 py-1 text-xs text-muted-foreground"><ContactRound className="size-3 text-primary" /> Application profile</span>
          <h1 className="text-2xl font-bold tracking-tight">Your details, ready for every form.</h1>
          <p className="text-sm text-muted-foreground">The browser extension reads these details and your master resume when you open an application.</p>
        </div>
      </div>

      {message && <p role="status" className="rounded-lg border border-border bg-card px-4 py-2 text-sm">{message}</p>}

      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><FileText className="size-4 text-primary" /> Core profile</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">Your name, contact details, experience, and education come from your account settings and master data.</p>
          {profile && <p className="text-sm">Connected as <strong>{profile.account}</strong></p>}
          <div className="flex flex-wrap gap-2">
            <Link href="/config" className={buttonVariants({ variant: "outline", size: "sm" })}>Edit contact details <ArrowRight className="size-3" /></Link>
            <Link href="/master-data" className={buttonVariants({ variant: "outline", size: "sm" })}>Edit master resume <ArrowRight className="size-3" /></Link>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Application details</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">These answers fill matching fields on application forms. Leave optional demographic answers blank if you prefer.</p>
          <div className="grid gap-4 sm:grid-cols-2">
            {fields.map(([key, label]) => (
              <label key={key} className="space-y-1.5 text-sm font-medium">{label}
                <Input value={extra[key] || ""} maxLength={500}
                  onChange={(event) => setExtra((current) => ({ ...current, [key]: event.target.value }))} />
              </label>
            ))}
          </div>
          <Button onClick={saveProfile} disabled={!profile || busy}>Save application details</Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Saved answers</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">Exact matching questions can use these answers again. Review them on each application.</p>
          <div className="space-y-3">
            {answers.map((answer) => (
              <div key={answer.id} className="flex gap-3 rounded-lg border border-border p-3">
                <div className="min-w-0 flex-1"><p className="font-medium">{answer.prompt}</p><p className="mt-1 whitespace-pre-wrap text-sm text-muted-foreground">{answer.content}</p></div>
                <Button variant="ghost" size="icon-sm" aria-label={`Delete ${answer.prompt}`} disabled={busy} onClick={() => removeAnswer(answer.id)}><Trash2 className="size-4" /></Button>
              </div>
            ))}
          </div>
          <div className="space-y-3 border-t border-border pt-4">
            <label className="block space-y-1.5 text-sm font-medium">Question<Input value={prompt} maxLength={2000} onChange={(event) => setPrompt(event.target.value)} placeholder="Why are you interested in this role?" /></label>
            <label className="block space-y-1.5 text-sm font-medium">Your answer<Textarea value={content} maxLength={10000} onChange={(event) => setContent(event.target.value)} /></label>
            <Button onClick={addAnswer} disabled={busy || prompt.trim().length < 3 || !content.trim()}><Plus className="size-4" /> Save answer</Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
