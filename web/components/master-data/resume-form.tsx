"use client";

/**
 * The resume, as sections rather than a file.
 *
 * One Save for the whole document, matching the single structured PUT. Sections
 * collapse for navigation, not for saving — eight independent dirty states would
 * be harder to reason about than the file this replaces.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, RotateCcw, Save } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ChangeReview } from "@/components/change-review";
import { flattenMaster } from "@/lib/master-flatten";
import { api, type MasterResume } from "@/lib/api";

import { SectionIdentity } from "./section-identity";
import { SectionSummaries } from "./section-summaries";
import { SectionSkills } from "./section-skills";
import { SectionEntries } from "./section-entries";

export function ResumeForm() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["resume-structured"],
    queryFn: () => api.getResumeStructured().then((r) => r.data),
  });

  const [draft, setDraft] = useState<MasterResume | null>(null);
  const [baseline, setBaseline] = useState<MasterResume | null>(null);

  // Seed once the server answers, and re-seed if the file changed underneath —
  // the Advanced tab writes the same file, so trusting stale state here is how
  // one view silently saves over the other's work.
  const serverKey = JSON.stringify(data ?? null);
  const baselineKey = JSON.stringify(baseline ?? null);
  if (data && serverKey !== baselineKey && draft === null) {
    setBaseline(data);
    setDraft(data);
  }

  const save = useMutation({
    mutationFn: () => api.putResumeStructured(draft ?? {}),
    onSuccess: async () => {
      setBaseline(draft);
      toast.success("Saved");
      await qc.invalidateQueries({ queryKey: ["resume-structured"] });
      await qc.invalidateQueries({ queryKey: ["resume"] });
      await qc.invalidateQueries({ queryKey: ["profile-strength"] });
    },
    onError: (e) => toast.error(String(e)),
  });

  if (isLoading || !draft || !baseline) {
    return <Skeleton className="h-[60svh] w-full" />;
  }

  const patch = (p: Partial<MasterResume>) => setDraft({ ...draft, ...p });
  const dirty = JSON.stringify(draft) !== JSON.stringify(baseline);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <ChangeReview
          before={flattenMaster(baseline)}
          after={flattenMaster(draft)}
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
        <SectionIdentity value={draft} onChange={patch} />
        <SectionSummaries value={draft} onChange={patch} />
        <SectionEntries kind="experience" value={draft} onChange={patch} />
        <SectionEntries kind="projects" value={draft} onChange={patch} />
        <SectionEntries kind="education" value={draft} onChange={patch} />
        <SectionSkills value={draft} onChange={patch} />
      </div>
    </div>
  );
}
