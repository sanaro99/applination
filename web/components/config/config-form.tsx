"use client";

/**
 * config.yaml as sections rather than a file.
 *
 * Four of them: what to search for, which boards to search, how documents come
 * out, and when to be reminded. The other four sections already have better
 * homes — `llm` on /workflows, `inbox` in the Gmail card, `user` in onboarding
 * — and `pricing` is a developer knob. All of them stay reachable through the
 * Advanced tab, which is also the escape hatch for the search fields this form
 * leaves alone (`last_n_hours`, `cache_ttl_days`).
 *
 * One Save for the document, matching the single structured PUT, and the same
 * change review the master-data forms use.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, RotateCcw, Save } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { ChangeReview } from "@/components/change-review";
import { SectionCard } from "@/components/master-data/section-card";
import { StringList } from "@/components/master-data/string-list";
import { flattenConfig } from "@/lib/config-flatten";
import { api, type ConfigSections } from "@/lib/api";

// Scrapers whose config key does not humanise into their real name. Anything
// absent falls back to the key with underscores opened out — a new scraper is
// a code change in src/scrapers/, so a missing entry reads sensibly rather
// than blank.
const SOURCE_LABELS: Record<string, string> = {
  themuse: "The Muse",
  jsearch: "JSearch (RapidAPI)",
  simplify_github: "Simplify / Pitt CSC list",
  greenhouse: "Greenhouse boards",
  lever: "Lever boards",
};

const sourceLabel = (key: string) =>
  SOURCE_LABELS[key] ?? key.replace(/_/g, " ");

export function ConfigForm() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["config-structured"],
    queryFn: () => api.getConfigStructured().then((r) => r.data),
  });

  const [draft, setDraft] = useState<ConfigSections | null>(null);
  const [baseline, setBaseline] = useState<ConfigSections | null>(null);

  // Re-seed when the file changed underneath: the Advanced tab writes the same
  // config.yaml, and trusting stale state is how one view saves over the other.
  const serverKey = JSON.stringify(data ?? null);
  if (data && serverKey !== JSON.stringify(baseline ?? null) && draft === null) {
    setBaseline(data);
    setDraft(data);
  }

  const save = useMutation({
    mutationFn: () => api.putConfigStructured(draft as ConfigSections),
    onSuccess: async () => {
      setBaseline(draft);
      toast.success("Saved");
      await qc.invalidateQueries({ queryKey: ["config-structured"] });
      await qc.invalidateQueries({ queryKey: ["config"] });
      await qc.invalidateQueries({ queryKey: ["search-keywords"] });
    },
    onError: (e) => toast.error(String(e)),
  });

  if (isLoading || !draft || !baseline) {
    return <Skeleton className="h-[60svh] w-full" />;
  }

  const dirty = JSON.stringify(draft) !== JSON.stringify(baseline);

  const setSearch = (p: Partial<ConfigSections["search"]>) =>
    setDraft({ ...draft, search: { ...draft.search, ...p } });
  const setSources = (p: Partial<ConfigSections["sources"]>) =>
    setDraft({ ...draft, sources: { ...draft.sources, ...p } });
  const setOutput = (p: Partial<ConfigSections["output"]>) =>
    setDraft({ ...draft, output: { ...draft.output, ...p } });
  const setReminders = (p: Partial<ConfigSections["reminders"]>) =>
    setDraft({ ...draft, reminders: { ...draft.reminders, ...p } });

  const enabledCount = draft.sources.toggles.filter((t) => t.enabled).length;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <ChangeReview
          before={flattenConfig(baseline)}
          after={flattenConfig(draft)}
        />
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={!dirty || save.isPending}
            onClick={() => setDraft(baseline)}
          >
            <RotateCcw className="size-3" /> Reset
          </Button>
          <Button
            size="sm"
            disabled={!dirty || save.isPending}
            onClick={() => save.mutate()}
          >
            {save.isPending ? (
              <Loader2 className="size-3 animate-spin" />
            ) : (
              <Save className="size-3" />
            )}
            Save
          </Button>
        </div>
      </div>

      <div className="space-y-2">
        <SectionCard
          title="What to search for"
          why="The keywords each run queries boards with, and how strict the ranker is."
          summary={`${draft.search.keywords.length} keywords`}
        >
          <div className="space-y-2">
            <Label>Roles and keywords</Label>
            <StringList
              value={draft.search.keywords}
              onChange={(keywords) => setSearch({ keywords })}
              itemLabel="keyword"
              placeholder="software engineer intern"
            />
          </div>

          <NumberField
            label="Minimum match score"
            hint="0-100. Jobs the ranker scores below this are dropped."
            value={draft.search.min_match_score}
            onChange={(min_match_score) => setSearch({ min_match_score })}
          />
          <NumberField
            label="Jobs per run"
            hint="How many top matches get a tailored resume and cover letter."
            value={draft.search.max_jobs_per_day}
            onChange={(max_jobs_per_day) => setSearch({ max_jobs_per_day })}
          />

          <ToggleRow
            label="Include remote roles"
            checked={draft.search.remote_ok}
            onChange={(remote_ok) => setSearch({ remote_ok })}
          />

          <div className="space-y-2">
            <Label>Onsite cities</Label>
            <StringList
              value={draft.search.onsite_cities}
              onChange={(onsite_cities) => setSearch({ onsite_cities })}
              itemLabel="city"
              placeholder="Seattle, WA"
            />
          </div>

          <div className="space-y-2">
            <Label>Countries</Label>
            <p className="text-xs text-muted-foreground">
              Two-letter codes. Used by the boards that support it.
            </p>
            <StringList
              value={draft.search.countries}
              onChange={(countries) => setSearch({ countries })}
              itemLabel="country"
              placeholder="us"
            />
          </div>
        </SectionCard>

        <SectionCard
          title="Job boards"
          why="Which sources a run fetches from. More boards means more candidates and a longer run."
          summary={`${enabledCount} of ${draft.sources.toggles.length} on`}
        >
          {draft.sources.toggles.map((toggle, i) => (
            <div
              key={toggle.key}
              className="flex items-center justify-between gap-3 py-1"
            >
              <div>
                <span className="text-sm capitalize">
                  {sourceLabel(toggle.key)}
                </span>
                <code className="ml-2 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                  {toggle.key}
                </code>
              </div>
              <Switch
                checked={toggle.enabled}
                onCheckedChange={(enabled) =>
                  setSources({
                    toggles: draft.sources.toggles.map((t, j) =>
                      j === i ? { ...t, enabled } : t,
                    ),
                  })
                }
              />
            </div>
          ))}

          <div className="space-y-2 border-t border-border pt-3">
            <Label>Extra Greenhouse companies</Label>
            <p className="text-xs text-muted-foreground">
              Board slugs, added on top of the built-in list. Take the slug from
              a company&apos;s careers URL: job-boards.greenhouse.io/<em>slug</em>.
            </p>
            <StringList
              value={draft.sources.greenhouse_extra_companies}
              onChange={(greenhouse_extra_companies) =>
                setSources({ greenhouse_extra_companies })
              }
              itemLabel="company"
              placeholder="stripe"
            />
          </div>
        </SectionCard>

        <SectionCard
          title="Documents"
          why="How the generated resume and cover letter are rendered."
          summary={`${draft.output.font_name} ${draft.output.base_font_size}pt`}
        >
          <ToggleRow
            label="Also convert to PDF"
            hint="Needs Microsoft Word or LibreOffice on the machine that runs it."
            checked={draft.output.produce_pdf}
            onChange={(produce_pdf) => setOutput({ produce_pdf })}
          />
          <div className="space-y-2">
            <Label>Font</Label>
            <Input
              value={draft.output.font_name}
              onChange={(e) => setOutput({ font_name: e.target.value })}
              className="max-w-xs"
            />
          </div>
          <NumberField
            label="Font size"
            hint="Points. Body text; headings render two points larger."
            step={0.5}
            value={draft.output.base_font_size}
            onChange={(base_font_size) => setOutput({ base_font_size })}
          />
          <NumberField
            label="Margins"
            hint="Inches, left and right. Top and bottom follow."
            step={0.05}
            value={draft.output.margins_inches}
            onChange={(margins_inches) => setOutput({ margins_inches })}
          />
        </SectionCard>

        <SectionCard
          title="Reminders"
          why="The daily digest of deadlines and applications that have gone quiet."
          summary={draft.reminders.digest_enabled ? "digest on" : "digest off"}
        >
          <ToggleRow
            label="Email a daily digest"
            hint="Sent through the same Gmail connection as inbox sync."
            checked={draft.reminders.digest_enabled}
            onChange={(digest_enabled) => setReminders({ digest_enabled })}
          />
          <div className="space-y-2">
            <Label>Send it to</Label>
            <Input
              value={draft.reminders.digest_to}
              placeholder="defaults to your account email"
              onChange={(e) => setReminders({ digest_to: e.target.value })}
              className="max-w-sm"
            />
          </div>
          <NumberField
            label="Deadline window"
            hint="Days ahead. Deadlines inside this window are surfaced."
            value={draft.reminders.deadline_window_days}
            onChange={(deadline_window_days) =>
              setReminders({ deadline_window_days })
            }
          />
          <NumberField
            label="Follow up after"
            hint="Days of silence before an application is nudged."
            value={draft.reminders.follow_up_days}
            onChange={(follow_up_days) => setReminders({ follow_up_days })}
          />
        </SectionCard>
      </div>
    </div>
  );
}

function NumberField({
  label,
  hint,
  value,
  step,
  onChange,
}: {
  label: string;
  hint?: string;
  value: number;
  step?: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
      <Input
        type="number"
        step={step}
        value={value}
        // An empty or half-typed box parses to NaN, which would travel to the
        // server as null and fail validation on a field the user is still
        // editing. Hold the last good number instead.
        onChange={(e) => {
          const next = Number(e.target.value);
          if (Number.isFinite(next)) onChange(next);
        }}
        className="max-w-32"
      />
    </div>
  );
}

function ToggleRow({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 py-1">
      <div>
        <span className="text-sm">{label}</span>
        {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
      </div>
      <Switch checked={checked} onCheckedChange={onChange} />
    </div>
  );
}
