"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Circle,
  Loader2,
  Sparkles,
  Upload,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api, type OnboardingStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

const PROVIDERS = [
  { id: "gemini", label: "Google Gemini", model: "gemini-2.5-flash", hint: "Free key at aistudio.google.com/apikey", needsKey: true },
  { id: "deepseek", label: "DeepSeek", model: "deepseek-chat", hint: "platform.deepseek.com", needsKey: true },
  { id: "mistral", label: "Mistral", model: "mistral-small-latest", hint: "console.mistral.ai", needsKey: true },
  { id: "openrouter", label: "OpenRouter", model: "tencent/hy3-preview:free", hint: "Free models at openrouter.ai/keys", needsKey: true },
  { id: "claude", label: "Anthropic Claude", model: "claude-haiku-4-5-20251001", hint: "console.anthropic.com", needsKey: true },
  { id: "ollama", label: "Ollama (local)", model: "llama3.2", hint: "Runs locally, no key needed", needsKey: false },
];

const STEPS = ["Welcome", "AI provider", "Your details", "Resume", "Voice & stories", "Search", "Finish"];

export default function OnboardingPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [step, setStep] = useState(0);

  const { data: status } = useQuery({
    queryKey: ["onboarding-status"],
    queryFn: () => api.onboardingStatus(),
    retry: false,
  });
  const refreshStatus = () =>
    qc.invalidateQueries({ queryKey: ["onboarding-status"] });

  const next = () => setStep((s) => Math.min(s + 1, STEPS.length - 1));
  const back = () => setStep((s) => Math.max(s - 1, 0));

  return (
    <div className="mx-auto flex min-h-svh max-w-5xl flex-col gap-6 p-6 sm:p-10">
      <header className="space-y-1">
        <div className="font-heading text-2xl font-extrabold tracking-tight">
          Appli<span className="text-primary">nation</span>
        </div>
        <p className="text-sm text-muted-foreground">
          Let&apos;s set up your job application pipeline. This takes a few minutes.
        </p>
      </header>

      <Stepper step={step} status={status} onJump={setStep} />

      <div className="flex-1">
        {step === 0 && <WelcomeStep onNext={next} />}
        {step === 1 && (
          <ProviderStep onSaved={refreshStatus} onNext={next} onBack={back} />
        )}
        {step === 2 && (
          <ContactStep onSaved={refreshStatus} onNext={next} onBack={back} />
        )}
        {step === 3 && (
          <ResumeStep onSaved={refreshStatus} onNext={next} onBack={back} />
        )}
        {step === 4 && (
          <VoiceStep onSaved={refreshStatus} onNext={next} onBack={back} />
        )}
        {step === 5 && (
          <SearchStep onSaved={refreshStatus} onNext={next} onBack={back} />
        )}
        {step === 6 && (
          <FinishStep
            status={status}
            onBack={back}
            onDone={async () => {
              await api.onboardingComplete();
              await refreshStatus();
              router.replace("/");
            }}
          />
        )}
      </div>
    </div>
  );
}

function Stepper({
  step,
  status,
  onJump,
}: {
  step: number;
  status?: OnboardingStatus;
  onJump: (n: number) => void;
}) {
  const done = (i: number): boolean => {
    if (!status) return false;
    switch (i) {
      case 1:
        return status.steps.provider;
      case 2:
        return status.steps.contact;
      case 3:
        return status.steps.resume;
      case 4:
        return status.steps.bio || status.steps.stories > 0;
      default:
        return false;
    }
  };
  return (
    <ol className="flex flex-wrap gap-2">
      {STEPS.map((label, i) => (
        <li key={label}>
          <button
            onClick={() => onJump(i)}
            className={cn(
              "flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors",
              i === step
                ? "border-primary bg-primary/10 text-primary"
                : "border-border text-muted-foreground hover:text-foreground",
            )}
          >
            {done(i) ? (
              <CheckCircle2 className="size-3.5 text-primary" />
            ) : (
              <Circle className="size-3.5" />
            )}
            {label}
          </button>
        </li>
      ))}
    </ol>
  );
}

function StepShell({
  title,
  children,
  footer,
}: {
  title: string;
  children: React.ReactNode;
  footer: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">{children}</CardContent>
      <div className="flex items-center justify-between gap-2 border-t border-border p-4">
        {footer}
      </div>
    </Card>
  );
}

function WelcomeStep({ onNext }: { onNext: () => void }) {
  return (
    <StepShell
      title="Welcome"
      footer={
        <>
          <span className="text-xs text-muted-foreground">
            Your data and API keys stay in local, gitignored files.
          </span>
          <Button onClick={onNext} className="gap-2">
            Get started <ArrowRight className="size-4" />
          </Button>
        </>
      }
    >
      <p className="text-sm text-muted-foreground">
        Applination fetches fresh job postings, ranks them against your background,
        tailors a one-page resume, and drafts a cover letter for each top match.
      </p>
      <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
        <li>Connect an LLM provider (several have free tiers).</li>
        <li>Add your contact details.</li>
        <li>Upload your resume — we extract it into an editable profile.</li>
        <li>Optionally draft your voice and a few stories with AI.</li>
        <li>Tell us what roles you want.</li>
      </ul>
    </StepShell>
  );
}

function ProviderStep({
  onSaved,
  onNext,
  onBack,
}: {
  onSaved: () => void;
  onNext: () => void;
  onBack: () => void;
}) {
  const [providerId, setProviderId] = useState("gemini");
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState<"save" | "test" | null>(null);
  const meta = PROVIDERS.find((p) => p.id === providerId)!;

  const save = async () => {
    setBusy("save");
    try {
      await api.setOnboardingProvider({
        provider: providerId,
        api_key: apiKey,
        model: meta.model,
        base_url: providerId === "ollama" ? "http://localhost:11434" : undefined,
        make_primary: true,
      });
      onSaved();
      toast.success(`${meta.label} saved as your primary provider`);
    } catch (e) {
      toast.error(String(e));
    } finally {
      setBusy(null);
    }
  };

  const test = async () => {
    setBusy("test");
    try {
      const res = await api.testProvider(providerId);
      if (res.ok) toast.success(`${meta.label} responded OK`);
      else toast.error(res.error || "Provider test failed");
    } catch (e) {
      toast.error(String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <StepShell
      title="Connect an AI provider"
      footer={
        <>
          <Button variant="ghost" onClick={onBack} className="gap-2">
            <ArrowLeft className="size-4" /> Back
          </Button>
          <div className="flex gap-2">
            <Button variant="outline" onClick={test} disabled={busy !== null}>
              {busy === "test" ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                "Test"
              )}
            </Button>
            <Button onClick={async () => { await save(); onNext(); }} disabled={busy !== null} className="gap-2">
              {busy === "save" ? <Loader2 className="size-4 animate-spin" /> : null}
              Save &amp; continue
            </Button>
          </div>
        </>
      }
    >
      <div className="grid gap-2">
        <Label>Provider</Label>
        <Select
          value={providerId}
          onValueChange={(v) => setProviderId(v ?? "gemini")}
        >
          <SelectTrigger className="w-full sm:w-80">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PROVIDERS.map((p) => (
              <SelectItem key={p.id} value={p.id}>
                {p.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-xs text-muted-foreground">{meta.hint}</p>
      </div>
      {meta.needsKey && (
        <div className="grid gap-2">
          <Label htmlFor="apikey">API key</Label>
          <Input
            id="apikey"
            type="password"
            placeholder="Paste your API key"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            className="w-full sm:w-[28rem]"
          />
          <p className="text-xs text-muted-foreground">
            Stored in your local config.yaml (gitignored). Model:{" "}
            <code>{meta.model}</code>
          </p>
        </div>
      )}
    </StepShell>
  );
}

function ContactStep({
  onSaved,
  onNext,
  onBack,
}: {
  onSaved: () => void;
  onNext: () => void;
  onBack: () => void;
}) {
  const [f, setF] = useState({
    full_name: "",
    email: "",
    phone: "",
    location_city: "",
    linkedin: "",
    github: "",
    portfolio: "",
  });
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setF((prev) => ({ ...prev, [k]: e.target.value }));

  const save = async () => {
    if (!f.full_name.trim() || !f.email.trim()) {
      toast.error("Name and email are required");
      return;
    }
    setBusy(true);
    try {
      await api.setOnboardingUser(f);
      onSaved();
      toast.success("Contact details saved");
      onNext();
    } catch (e) {
      toast.error(String(e));
    } finally {
      setBusy(false);
    }
  };

  const field = (k: keyof typeof f, label: string, placeholder = "") => (
    <div className="grid gap-1.5">
      <Label htmlFor={k}>{label}</Label>
      <Input id={k} value={f[k]} onChange={set(k)} placeholder={placeholder} />
    </div>
  );

  return (
    <StepShell
      title="Your details"
      footer={
        <>
          <Button variant="ghost" onClick={onBack} className="gap-2">
            <ArrowLeft className="size-4" /> Back
          </Button>
          <Button onClick={save} disabled={busy} className="gap-2">
            {busy ? <Loader2 className="size-4 animate-spin" /> : null}
            Save &amp; continue
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {field("full_name", "Full name *", "Jordan Lee")}
        {field("email", "Email *", "jordan@example.com")}
        {field("phone", "Phone", "+1 (555) 555-5555")}
        {field("location_city", "Location", "Seattle, WA")}
        {field("linkedin", "LinkedIn", "linkedin.com/in/you")}
        {field("github", "GitHub", "github.com/you")}
        {field("portfolio", "Portfolio", "yoursite.com")}
      </div>
    </StepShell>
  );
}

function ResumeStep({
  onSaved,
  onNext,
  onBack,
}: {
  onSaved: () => void;
  onNext: () => void;
  onBack: () => void;
}) {
  const [pasted, setPasted] = useState("");
  const [yaml, setYaml] = useState("");
  const [busy, setBusy] = useState<"import" | "save" | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const handleFile = async (file: File) => {
    setBusy("import");
    try {
      const res = await api.importResumeFile(file);
      setYaml(res.text);
      toast.success("Resume extracted — review and edit below");
    } catch (e) {
      toast.error(String(e));
    } finally {
      setBusy(null);
    }
  };

  const importText = async () => {
    setBusy("import");
    try {
      const res = await api.importResumeText({ text: pasted });
      setYaml(res.text);
      toast.success("Resume extracted — review and edit below");
    } catch (e) {
      toast.error(String(e));
    } finally {
      setBusy(null);
    }
  };

  const save = async () => {
    if (!yaml.trim()) {
      toast.error("Import or paste your resume first");
      return;
    }
    setBusy("save");
    try {
      await api.putResume(yaml);
      onSaved();
      toast.success("Master resume saved");
      onNext();
    } catch (e) {
      toast.error(String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <StepShell
      title="Import your resume"
      footer={
        <>
          <Button variant="ghost" onClick={onBack} className="gap-2">
            <ArrowLeft className="size-4" /> Back
          </Button>
          <Button onClick={save} disabled={busy !== null} className="gap-2">
            {busy === "save" ? <Loader2 className="size-4 animate-spin" /> : null}
            Save &amp; continue
          </Button>
        </>
      }
    >
      <p className="text-sm text-muted-foreground">
        Upload your existing resume (PDF, DOCX, or TXT) and we extract it into an
        editable profile, or paste the text. Everything is grounded in what you
        provide — nothing is invented.
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,.docx,.txt"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleFile(file);
          }}
        />
        <Button
          variant="outline"
          className="gap-2"
          onClick={() => fileRef.current?.click()}
          disabled={busy !== null}
        >
          {busy === "import" ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Upload className="size-4" />
          )}
          Upload file
        </Button>
        <span className="text-xs text-muted-foreground">or paste below</span>
      </div>
      <Textarea
        placeholder="Paste your resume text here…"
        value={pasted}
        onChange={(e) => setPasted(e.target.value)}
        className="min-h-28"
      />
      <Button
        variant="secondary"
        size="sm"
        className="gap-2"
        onClick={importText}
        disabled={busy !== null || pasted.trim().length < 40}
      >
        <Sparkles className="size-4" /> Extract from pasted text
      </Button>

      {yaml && (
        <div className="grid gap-1.5">
          <Label>Master resume (YAML) — review and edit</Label>
          <Textarea
            value={yaml}
            onChange={(e) => setYaml(e.target.value)}
            className="min-h-80 font-mono text-xs"
          />
        </div>
      )}
    </StepShell>
  );
}

function VoiceStep({
  onSaved,
  onNext,
  onBack,
}: {
  onSaved: () => void;
  onNext: () => void;
  onBack: () => void;
}) {
  const [bio, setBio] = useState("");
  const [storyDesc, setStoryDesc] = useState("");
  const [busy, setBusy] = useState<"bio" | "story" | null>(null);

  const saveBio = async () => {
    setBusy("bio");
    try {
      await api.putBio(bio);
      onSaved();
      toast.success("Voice saved");
    } catch (e) {
      toast.error(String(e));
    } finally {
      setBusy(null);
    }
  };

  const genStory = async () => {
    if (storyDesc.trim().length < 20) {
      toast.error("Describe the story in a bit more detail");
      return;
    }
    setBusy("story");
    try {
      const story = await api.generateStory({ description: storyDesc });
      await api.putStory(story.filename, story.text);
      onSaved();
      setStoryDesc("");
      toast.success(`Saved story: ${String(story.fields.title ?? story.filename)}`);
    } catch (e) {
      toast.error(String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <StepShell
      title="Voice & stories (optional)"
      footer={
        <>
          <Button variant="ghost" onClick={onBack} className="gap-2">
            <ArrowLeft className="size-4" /> Back
          </Button>
          <Button onClick={onNext} className="gap-2">
            Continue <ArrowRight className="size-4" />
          </Button>
        </>
      }
    >
      <p className="text-sm text-muted-foreground">
        Stories and a short voice guide make your cover letters and interview
        prep sound like you. You can skip this and add them later on the
        Master&nbsp;data page.
      </p>
      <div className="grid gap-1.5">
        <Label>Your voice (how you write — tone, what you care about)</Label>
        <Textarea
          value={bio}
          onChange={(e) => setBio(e.target.value)}
          placeholder="Direct, specific, no filler. I care about shipping things people use…"
          className="min-h-28"
        />
        <Button
          variant="secondary"
          size="sm"
          className="w-fit"
          onClick={saveBio}
          disabled={busy !== null || !bio.trim()}
        >
          {busy === "bio" ? <Loader2 className="size-4 animate-spin" /> : null}
          Save voice
        </Button>
      </div>
      <div className="grid gap-1.5">
        <Label>Draft a story with AI (describe a real project or win)</Label>
        <Textarea
          value={storyDesc}
          onChange={(e) => setStoryDesc(e.target.value)}
          placeholder="At my last job I built X that did Y, the hard part was Z…"
          className="min-h-24"
        />
        <Button
          variant="secondary"
          size="sm"
          className="w-fit gap-2"
          onClick={genStory}
          disabled={busy !== null}
        >
          {busy === "story" ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Sparkles className="size-4" />
          )}
          Generate &amp; save story
        </Button>
      </div>
    </StepShell>
  );
}

function SearchStep({
  onSaved,
  onNext,
  onBack,
}: {
  onSaved: () => void;
  onNext: () => void;
  onBack: () => void;
}) {
  const [keywords, setKeywords] = useState(
    "software engineer\nmachine learning\ndata science",
  );
  const [remote, setRemote] = useState(true);
  const [cities, setCities] = useState("Remote");
  const [countries, setCountries] = useState("us");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    const kw = keywords
      .split(/[\n,]/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (kw.length === 0) {
      toast.error("Add at least one keyword");
      return;
    }
    setBusy(true);
    try {
      await api.setOnboardingSearch({
        keywords: kw,
        remote_ok: remote,
        onsite_cities: cities.split(",").map((s) => s.trim()).filter(Boolean),
        countries: countries.split(",").map((s) => s.trim().toLowerCase()).filter(Boolean),
      });
      onSaved();
      toast.success("Search preferences saved");
      onNext();
    } catch (e) {
      toast.error(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <StepShell
      title="What roles do you want?"
      footer={
        <>
          <Button variant="ghost" onClick={onBack} className="gap-2">
            <ArrowLeft className="size-4" /> Back
          </Button>
          <Button onClick={save} disabled={busy} className="gap-2">
            {busy ? <Loader2 className="size-4 animate-spin" /> : null}
            Save &amp; continue
          </Button>
        </>
      }
    >
      <div className="grid gap-1.5">
        <Label>Search keywords (one per line)</Label>
        <Textarea
          value={keywords}
          onChange={(e) => setKeywords(e.target.value)}
          className="min-h-28"
        />
        <p className="text-xs text-muted-foreground">
          Be specific. Add &quot;intern&quot;, &quot;new grad&quot;, or
          &quot;senior&quot; to match the level you want.
        </p>
      </div>
      <div className="flex items-center gap-3">
        <Switch checked={remote} onCheckedChange={setRemote} id="remote" />
        <Label htmlFor="remote">Include remote roles</Label>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-1.5">
          <Label>Onsite cities (comma-separated)</Label>
          <Input value={cities} onChange={(e) => setCities(e.target.value)} />
        </div>
        <div className="grid gap-1.5">
          <Label>Countries (ISO codes)</Label>
          <Input
            value={countries}
            onChange={(e) => setCountries(e.target.value)}
          />
        </div>
      </div>
    </StepShell>
  );
}

function FinishStep({
  status,
  onBack,
  onDone,
}: {
  status?: OnboardingStatus;
  onBack: () => void;
  onDone: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const ready = status?.can_run ?? false;
  const row = (label: string, ok: boolean) => (
    <li className="flex items-center gap-2 text-sm">
      {ok ? (
        <CheckCircle2 className="size-4 text-primary" />
      ) : (
        <Circle className="size-4 text-muted-foreground" />
      )}
      {label}
    </li>
  );

  return (
    <StepShell
      title="You're all set"
      footer={
        <>
          <Button variant="ghost" onClick={onBack} className="gap-2">
            <ArrowLeft className="size-4" /> Back
          </Button>
          <Button
            onClick={async () => {
              setBusy(true);
              try {
                await onDone();
              } finally {
                setBusy(false);
              }
            }}
            disabled={busy}
            className="gap-2"
          >
            {busy ? <Loader2 className="size-4 animate-spin" /> : null}
            Finish &amp; go to dashboard
          </Button>
        </>
      }
    >
      <ul className="space-y-2">
        {row("AI provider connected", status?.steps.provider ?? false)}
        {row("Contact details added", status?.steps.contact ?? false)}
        {row("Master resume saved", status?.steps.resume ?? false)}
        {row(
          `Stories added (${status?.steps.stories ?? 0})`,
          (status?.steps.stories ?? 0) > 0,
        )}
      </ul>
      {!ready && (
        <p className="text-sm text-muted-foreground">
          You can still finish — but a provider, contact details, and a resume are
          required before you can run the pipeline. You can complete any missing
          steps from the Setup pages later.
        </p>
      )}
    </StepShell>
  );
}
