"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Bookmark, Copy, Loader2, PenLine, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { Markdown } from "@/components/coach/markdown";
import { GroundPicker } from "@/components/coach/ground-picker";

export default function EssayPage() {
  const qc = useQueryClient();
  const [prompt, setPrompt] = useState("");
  const [wordLimit, setWordLimit] = useState("");
  const [instructions, setInstructions] = useState("");
  const [appId, setAppId] = useState<number | null>(null);
  const [draft, setDraft] = useState<string | null>(null);

  const apps = useQuery({
    queryKey: ["applications", "all"],
    queryFn: () => api.listApplications(),
  });
  const groundedLabel =
    appId != null
      ? (() => {
          const a = (apps.data ?? []).find((x) => x.id === appId);
          return a ? `${a.company} — ${a.title}` : null;
        })()
      : null;

  const generate = useMutation({
    mutationFn: () =>
      api.draftEssay({
        prompt: prompt.trim(),
        word_limit: wordLimit ? Number(wordLimit) : undefined,
        application_id: appId ?? undefined,
        instructions: instructions.trim() || undefined,
      }),
    onSuccess: (d) => setDraft(d.content),
    onError: (e) => toast.error(`Draft failed: ${String(e)}`),
  });

  const save = useMutation({
    mutationFn: () =>
      api.saveAnswer({
        content: draft ?? "",
        prompt: prompt.trim() || undefined,
        application_id: appId ?? undefined,
        tags: ["essay"],
      }),
    onSuccess: () => {
      toast.success("Saved to answer bank");
      qc.invalidateQueries({ queryKey: ["chat", "answers"] });
    },
    onError: (e) => toast.error(String(e)),
  });

  const wordCount = draft ? draft.trim().split(/\s+/).filter(Boolean).length : 0;

  return (
    <div className="mx-auto grid max-w-6xl gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <PenLine className="size-4 text-primary" /> Essay / short-answer
            drafter
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label className="text-sm">Prompt / question</Label>
            <Textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Paste the scholarship or application prompt…"
              className="min-h-28"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label className="text-sm">Word limit (optional)</Label>
              <Input
                type="number"
                min={1}
                value={wordLimit}
                onChange={(e) => setWordLimit(e.target.value)}
                placeholder="e.g. 250"
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-sm">Job context (optional)</Label>
              <GroundPicker
                apps={apps.data ?? []}
                applicationId={appId}
                applicationLabel={groundedLabel}
                onChange={setAppId}
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label className="text-sm">Extra instructions (optional)</Label>
            <Input
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              placeholder="e.g. emphasize leadership; warm tone"
            />
          </div>
          <Button
            className="w-full gap-2"
            onClick={() => generate.mutate()}
            disabled={!prompt.trim() || generate.isPending}
          >
            {generate.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Sparkles className="size-4" />
            )}
            Draft answer
          </Button>
        </CardContent>
      </Card>

      <Card className="flex flex-col">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Draft</CardTitle>
          {draft && (
            <span className="text-xs text-muted-foreground">
              {wordCount} words
            </span>
          )}
        </CardHeader>
        <CardContent className="flex-1">
          {generate.isPending ? (
            <div className="flex items-center gap-2 py-10 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Drafting in your
              voice…
            </div>
          ) : draft ? (
            <div className="space-y-4">
              <div className="rounded-xl border border-border bg-background p-4">
                <Markdown>{draft}</Markdown>
              </div>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-2"
                  onClick={() => {
                    navigator.clipboard.writeText(draft);
                    toast.success("Copied");
                  }}
                >
                  <Copy className="size-3.5" /> Copy
                </Button>
                <Button
                  size="sm"
                  className="gap-2"
                  onClick={() => save.mutate()}
                  disabled={save.isPending}
                >
                  {save.isPending ? (
                    <Loader2 className="size-3.5 animate-spin" />
                  ) : (
                    <Bookmark className="size-3.5" />
                  )}
                  Save to answer bank
                </Button>
              </div>
            </div>
          ) : (
            <p className="py-10 text-center text-sm text-muted-foreground">
              Your drafted answer will appear here, grounded in your real
              stories.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
