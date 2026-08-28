"use client";

/**
 * One story, as fields rather than a file.
 *
 * The frontmatter is structured data that decides which story a cover letter
 * gets built from; the body is prose and stays a textarea, because prose is
 * what it is. Same Form / Advanced split as the resume, same single Save for
 * the whole document.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, RotateCcw, Save } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { ChangeReview } from "@/components/change-review";
import { flattenStory } from "@/lib/story-flatten";
import { api, type StoryDoc } from "@/lib/api";

import { SectionCard } from "./section-card";
import { TagPicker } from "./tag-picker";

export function StoryForm({ name }: { name: string }) {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["story-structured", name],
    queryFn: () => api.getStoryStructured(name).then((r) => r.data),
  });
  // The taxonomy is a committed file: it cannot change while the tab is open.
  const { data: taxonomy } = useQuery({
    queryKey: ["story-taxonomy"],
    queryFn: () => api.getStoryTaxonomy().then((r) => r.groups),
    staleTime: Infinity,
  });

  const [draft, setDraft] = useState<StoryDoc | null>(null);
  const [baseline, setBaseline] = useState<StoryDoc | null>(null);

  // Re-seed when the file changed underneath — the Advanced tab writes the same
  // file, and trusting stale state here is how one view saves over the other.
  const serverKey = JSON.stringify(data ?? null);
  if (data && serverKey !== JSON.stringify(baseline ?? null) && draft === null) {
    setBaseline(data);
    setDraft(data);
  }

  const save = useMutation({
    mutationFn: () => api.putStoryStructured(name, draft ?? {}),
    onSuccess: async () => {
      setBaseline(draft);
      toast.success("Saved");
      await qc.invalidateQueries({ queryKey: ["story-structured", name] });
      await qc.invalidateQueries({ queryKey: ["story", name] });
      await qc.invalidateQueries({ queryKey: ["stories"] });
      await qc.invalidateQueries({ queryKey: ["profile-strength"] });
    },
    onError: (e) => toast.error(String(e)),
  });

  if (isLoading || !draft || !baseline) {
    return <Skeleton className="h-[55svh] w-full" />;
  }

  const patch = (p: Partial<StoryDoc>) => setDraft({ ...draft, ...p });
  const dirty = JSON.stringify(draft) !== JSON.stringify(baseline);
  const groups = taxonomy ?? [];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <ChangeReview
          before={flattenStory(baseline)}
          after={flattenStory(draft)}
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
          title="How this story gets matched"
          why="Tags outrank the body twentyfold when picking a story for a cover letter."
          summary={`${draft.tags.length} tags`}
          defaultOpen
        >
          <div className="space-y-2">
            <Label>Title</Label>
            <Input
              value={draft.title}
              placeholder="Short descriptive name"
              onChange={(e) => patch({ title: e.target.value })}
            />
          </div>

          <div className="space-y-2">
            <Label>Tags</Label>
            <p className="text-xs text-muted-foreground">
              What this story is about — technical areas and specific tech.
            </p>
            <TagPicker
              field="tags"
              groups={groups}
              value={draft.tags}
              onChange={(tags) => patch({ tags })}
              placeholder="Search or type a tag…"
            />
          </div>

          <div className="space-y-2">
            <Label>Fits these roles</Label>
            <TagPicker
              field="role_fit"
              groups={groups}
              value={draft.role_fit}
              onChange={(role_fit) => patch({ role_fit })}
              placeholder="Search or type a role type…"
            />
          </div>

          <div className="space-y-2">
            <Label>Fits these companies</Label>
            <TagPicker
              field="company_fit"
              groups={groups}
              value={draft.company_fit}
              onChange={(company_fit) => patch({ company_fit })}
              placeholder="Search or type a company type…"
            />
          </div>

          <div className="space-y-2">
            <Label>Hook</Label>
            <p className="text-xs text-muted-foreground">
              One sentence a cover letter can quote directly.
            </p>
            <Textarea
              value={draft.one_liner}
              placeholder="Cut detection time by 60% for 30+ teams."
              className="min-h-16"
              onChange={(e) => patch({ one_liner: e.target.value })}
            />
          </div>
        </SectionCard>

        <SectionCard
          title="The story itself"
          why="Context, what you did, what was hard, what came of it. Around 200-300 words."
          summary={`${draft.body.trim() ? draft.body.trim().split(/\s+/).length : 0} words`}
          defaultOpen
        >
          <Textarea
            value={draft.body}
            onChange={(e) => patch({ body: e.target.value })}
            className="min-h-[40svh] font-mono text-xs leading-relaxed"
            spellCheck={false}
          />
        </SectionCard>
      </div>
    </div>
  );
}
