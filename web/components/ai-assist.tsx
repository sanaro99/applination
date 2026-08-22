"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { ProviderSelect } from "@/components/provider-select";
import { SimulatedChip } from "@/components/demo-banner";

/**
 * Reusable "instruct the LLM to revise this" panel. Mirrors the resume
 * TweakPanel pattern. On success, hands the resulting text to `onResult` so the
 * parent can drop it into its editor for review before saving.
 */
export function AiAssist({
  onResult,
  run,
  placeholder = "e.g. tighten the second paragraph and add the metric",
  label = "Improve with AI",
}: {
  onResult: (text: string) => void;
  run: (instruction: string, provider: string | null) => Promise<string>;
  placeholder?: string;
  label?: string;
}) {
  const [instruction, setInstruction] = useState("");
  const [provider, setProvider] = useState<string | null>(null);

  const go = useMutation({
    mutationFn: () => run(instruction.trim(), provider),
    onSuccess: (text) => {
      onResult(text);
      toast.success("Draft updated — review and Save");
    },
    onError: (e) => toast.error(String(e)),
  });

  return (
    <div className="space-y-2 rounded-xl border border-border bg-muted/30 p-3">
      <div className="flex items-center justify-between gap-2">
        <Label className="flex items-center gap-1.5 text-sm font-medium">
          <Sparkles className="size-3.5 text-primary" /> {label}
          <SimulatedChip />
        </Label>
        <ProviderSelect
          value={provider}
          onChange={setProvider}
          className="h-8 w-40 text-xs"
        />
      </div>
      <Textarea
        value={instruction}
        onChange={(e) => setInstruction(e.target.value)}
        placeholder={placeholder}
        className="min-h-16 text-sm"
      />
      <Button
        size="sm"
        className="gap-2"
        onClick={() => go.mutate()}
        disabled={!instruction.trim() || go.isPending}
      >
        {go.isPending ? (
          <Loader2 className="size-3.5 animate-spin" />
        ) : (
          <Sparkles className="size-3.5" />
        )}
        Generate
      </Button>
    </div>
  );
}
