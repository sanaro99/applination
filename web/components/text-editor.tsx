"use client";

import { useEffect, useRef, useState } from "react";
import { Save, RotateCcw, Loader2 } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ChangeReview } from "@/components/change-review";
import { cn } from "@/lib/utils";

interface TextEditorProps {
  onSave: (text: string) => Promise<unknown>;
  language?: "yaml" | "markdown" | "text";
  minHeight?: string;
  // Uncontrolled mode: seed from `initial` (re-syncs if `initial` changes).
  initial?: string;
  // Controlled mode: parent owns the text (used so an AI panel can replace it
  // and so the panel can read the current editor content). `baseline` is the
  // text Save/Reset compare against (e.g. the on-disk version).
  value?: string;
  onValueChange?: (v: string) => void;
  baseline?: string;
}

export function TextEditor({
  onSave,
  language = "text",
  minHeight = "min-h-[60svh]",
  initial,
  value,
  onValueChange,
  baseline,
}: TextEditorProps) {
  const controlled = value !== undefined && onValueChange !== undefined;
  const [internal, setInternal] = useState(initial ?? "");
  const lastInitial = useRef(initial);
  useEffect(() => {
    if (!controlled && initial !== undefined && initial !== lastInitial.current) {
      setInternal(initial);
      lastInitial.current = initial;
    }
  }, [initial, controlled]);

  const val = controlled ? (value as string) : internal;
  const setVal = controlled ? (onValueChange as (v: string) => void) : setInternal;
  const base = baseline ?? initial ?? "";
  const dirty = val !== base;

  const save = useMutation({
    mutationFn: () => Promise.resolve(onSave(val)),
    onSuccess: () => toast.success("Saved"),
    onError: (e) => toast.error(String(e)),
  });

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs uppercase tracking-wide text-muted-foreground">
          {language === "yaml"
            ? "YAML"
            : language === "markdown"
              ? "Markdown"
              : "Text"}
        </span>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={!dirty || save.isPending}
            onClick={() => setVal(base)}
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
      {dirty ? (
        <ChangeReview before={base.split("\n")} after={val.split("\n")} />
      ) : null}
      <Textarea
        value={val}
        onChange={(e) => setVal(e.target.value)}
        className={cn("font-mono text-xs leading-relaxed", minHeight)}
        spellCheck={false}
      />
    </div>
  );
}
