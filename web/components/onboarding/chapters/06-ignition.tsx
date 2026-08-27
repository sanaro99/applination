"use client";

/**
 * Chapter 6 — ignition.
 *
 * Contact details and the provider key sit together because they share one
 * justification: to put your name on a document I need your details, and to
 * actually write it I need a provider.
 *
 * Then the enrichment cascade runs, client-driven and step by step, so each
 * completed step visibly fills its part of the profile meter. That cascade *is* the celebration —
 * the reward for having deferred the key rather than an apology for it — which
 * is why a single failing step is retryable in place and never abandons the
 * rest.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Check, ExternalLink, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, type EnrichStep, type ProviderSetup } from "@/lib/api";
import { SAMPLE } from "@/lib/sample-data";
import { cn } from "@/lib/utils";

import { JourneyShell } from "../journey-shell";
import { useJourneyStore } from "../use-journey-store";

type Contact = {
  full_name: string;
  email: string;
  phone: string;
  location_city: string;
};

/** Cheap client-side check, so an obviously malformed key never costs a call. */
function keyLooksWrong(provider: ProviderSetup, key: string): string | null {
  if (!provider.needs_key) return null;
  const trimmed = key.trim();
  if (!trimmed) return "Paste your key, or skip this for now.";
  if (provider.key_shape.prefix && !trimmed.startsWith(provider.key_shape.prefix))
    return `${provider.label} keys start with "${provider.key_shape.prefix}".`;
  if (trimmed.length < provider.key_shape.min_len)
    return "That looks too short to be a whole key.";
  return null;
}

export function ChapterIgnition({ onBack }: { onBack: () => void }) {
  const router = useRouter();
  const qc = useQueryClient();
  const markSample = useJourneyStore((s) => s.markSample);
  const resetJourney = useJourneyStore((s) => s.reset);

  const [contact, setContact] = useState<Contact>({
    full_name: "",
    email: "",
    phone: "",
    location_city: "",
  });
  const [providerId, setProviderId] = useState("gemini");
  const [apiKey, setApiKey] = useState("");
  const [cascade, setCascade] = useState<EnrichStep[] | null>(null);

  const { data } = useQuery({
    queryKey: ["provider-setup"],
    queryFn: () => api.providerSetup(),
    retry: false,
  });
  const providers = data?.providers ?? [];
  const chosen = providers.find((p) => p.id === providerId);

  const ignite = useMutation({
    mutationFn: async () => {
      if (contact.full_name.trim() && contact.email.trim()) {
        await api.setOnboardingUser(contact);
      }
      if (chosen) {
        await api.setOnboardingProvider({
          provider: chosen.id,
          api_key: apiKey.trim(),
          model: chosen.model,
          base_url:
            chosen.id === "ollama" ? "http://localhost:11434" : undefined,
          make_primary: true,
        });
      }
      void qc.invalidateQueries({ queryKey: ["profile-strength"] });
      void qc.invalidateQueries({ queryKey: ["onboarding-status"] });
      return (await api.enrichPlan()).steps;
    },
    onSuccess: (steps) => setCascade(steps),
    onError: (e) => toast.error(String(e)),
  });

  const finish = async () => {
    try {
      await api.onboardingComplete();
    } catch (e) {
      toast.error(String(e));
    }
    resetJourney();
    void qc.invalidateQueries({ queryKey: ["onboarding-status"] });
    void qc.invalidateQueries({ queryKey: ["profile-strength"] });
    router.replace("/");
  };

  if (cascade) {
    return <Cascade steps={cascade} onDone={finish} />;
  }

  const keyProblem = chosen ? keyLooksWrong(chosen, apiKey) : null;

  return (
    <JourneyShell
      eyebrow="Chapter 6"
      heading="Last thing."
      onBack={onBack}
      onNext={() => {
        if (keyProblem && apiKey.trim()) {
          toast.error(keyProblem);
          return;
        }
        ignite.mutate();
      }}
      nextLabel="Finish setup"
      busy={ignite.isPending}
      onSample={() => {
        setContact({ ...SAMPLE.contact });
        markSample("ignition");
        void api
          .markSampleUsed()
          .then(() => qc.invalidateQueries({ queryKey: ["onboarding-status"] }))
          .catch(() => {});
      }}
      onSkip={finish}
      footerNote="Skip this and everything you told me stays — you'll land on the dashboard with drafts intact."
    >
      <p className="text-base text-muted-foreground">
        To put your name on a document I need your details. To actually write it,
        I need a provider.
      </p>

      <div className="grid gap-4 sm:grid-cols-2">
        {(
          [
            ["full_name", "Full name"],
            ["email", "Email"],
            ["phone", "Phone"],
            ["location_city", "Location"],
          ] as [keyof Contact, string][]
        ).map(([key, label]) => (
          <div key={key} className="grid gap-1.5">
            <Label htmlFor={key}>{label}</Label>
            <Input
              id={key}
              value={contact[key]}
              onChange={(e) =>
                setContact((c) => ({ ...c, [key]: e.target.value }))
              }
            />
          </div>
        ))}
      </div>

      <div className="space-y-3 pt-2">
        {providers.map((p) => (
          <div
            key={p.id}
            className={cn(
              "rounded-lg border p-4 transition-colors",
              p.id === providerId
                ? "border-primary bg-primary/5"
                : "border-border",
            )}
          >
            <button
              onClick={() => setProviderId(p.id)}
              className="flex w-full items-start justify-between gap-3 text-left"
            >
              <span>
                <span className="flex items-center gap-2 font-medium">
                  {p.label}
                  {p.recommended ? (
                    <span className="rounded-full bg-primary/15 px-2 py-0.5 text-xs text-primary">
                      Recommended
                    </span>
                  ) : null}
                </span>
                <span className="mt-1 block text-sm text-muted-foreground">
                  {p.why}
                </span>
              </span>
              {p.id === providerId ? (
                <Check className="size-4 shrink-0 text-primary" />
              ) : null}
            </button>

            {p.id === providerId ? (
              <div className="mt-4 space-y-3">
                <ol className="list-decimal space-y-1 pl-5 text-sm text-muted-foreground">
                  {p.steps.map((step) => (
                    <li key={step}>{step}</li>
                  ))}
                </ol>
                <a
                  href={p.console_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={buttonVariants({ size: "sm" })}
                >
                  Open {p.label} <ExternalLink className="size-3.5" />
                </a>
                {p.needs_key ? (
                  <div className="grid gap-1.5">
                    <Label htmlFor="journey-api-key">API key</Label>
                    <Input
                      id="journey-api-key"
                      type="password"
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      placeholder="Paste your API key"
                    />
                    {apiKey.trim() && keyProblem ? (
                      <p className="text-xs text-destructive">{keyProblem}</p>
                    ) : null}
                  </div>
                ) : null}
                <p className="text-xs text-muted-foreground">{p.cost_note}</p>
                {p.stale ? (
                  <p className="text-xs text-muted-foreground">
                    These steps were checked on {p.verified_on} and may have
                    moved — the link is the thing to trust.
                  </p>
                ) : null}
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </JourneyShell>
  );
}

/**
 * The cascade. One step at a time, each invalidating the strength query so the
 * profile meter re-reads real state rather than animating on a timer.
 */
function Cascade({
  steps,
  onDone,
}: {
  steps: EnrichStep[];
  onDone: () => void;
}) {
  const qc = useQueryClient();
  const [index, setIndex] = useState(0);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [started, setStarted] = useState(false);

  const runFrom = async (from: number) => {
    setRunning(true);
    setError(null);
    for (let i = from; i < steps.length; i += 1) {
      setIndex(i);
      try {
        await api.enrichStep(steps[i].id);
      } catch (e) {
        setError(String(e));
        setRunning(false);
        return;
      }
      await qc.invalidateQueries({ queryKey: ["profile-strength"] });
    }
    setIndex(steps.length);
    setRunning(false);
  };

  // Kicked off by a click rather than an effect: the first step is a real,
  // billable model call, and starting one the moment a component mounts is how
  // a stray remount turns into two.
  const done = started && !running && !error && index >= steps.length;

  return (
    <JourneyShell
      eyebrow="Almost there"
      heading={
        steps.length === 0
          ? "Nothing left to do."
          : done
            ? "That's your profile."
            : "Putting it together."
      }
      onNext={
        done || steps.length === 0
          ? onDone
          : started
            ? undefined
            : () => {
                setStarted(true);
                void runFrom(0);
              }
      }
      nextLabel={done || steps.length === 0 ? "Take me in" : "Start"}
      busy={running}
    >
      {steps.length === 0 ? (
        <p className="text-base text-muted-foreground">
          There was nothing waiting to be turned into master data. You can add
          more any time from Master data.
        </p>
      ) : (
        <ul className="space-y-2">
          {steps.map((step, i) => {
            const state =
              i < index ? "done" : i === index && running ? "running" : "pending";
            return (
              <li
                key={step.id}
                className="flex items-center gap-3 rounded-md border border-border/60 px-3 py-2 text-sm"
              >
                {state === "done" ? (
                  <Check className="size-4 text-primary" />
                ) : state === "running" ? (
                  <Loader2 className="size-4 animate-spin text-primary" />
                ) : i === index && error ? (
                  <AlertCircle className="size-4 text-destructive" />
                ) : (
                  <span className="size-4" />
                )}
                <span
                  className={cn(
                    state === "pending" && "text-muted-foreground",
                  )}
                >
                  {step.label}
                </span>
              </li>
            );
          })}
        </ul>
      )}

      {error ? (
        <div className="space-y-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3">
          <p className="text-sm text-destructive">{error}</p>
          <div className="flex gap-2">
            <Button size="sm" onClick={() => void runFrom(index)}>
              Retry this step
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => void runFrom(index + 1)}
            >
              Skip it
            </Button>
          </div>
        </div>
      ) : null}
    </JourneyShell>
  );
}
