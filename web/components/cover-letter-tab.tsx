"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2, Pencil, Save, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";

export function CoverLetterTab({
  appId,
  coverPdfUrl,
}: {
  appId: number;
  coverPdfUrl: string;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  // Bumped after a save to bust the PDF iframe cache so the re-render shows.
  const [reloadKey, setReloadKey] = useState(0);

  const cover = useQuery({
    queryKey: ["cover-letter", appId],
    queryFn: () => api.getCoverLetter(appId),
    enabled: editing,
  });

  useEffect(() => {
    if (cover.data && editing) setText(cover.data.text);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cover.data, editing]);

  const save = useMutation({
    mutationFn: () => api.saveCoverLetter(appId, text),
    onSuccess: () => {
      toast.success("Cover letter re-rendered");
      setEditing(false);
      setReloadKey((k) => k + 1);
    },
    onError: (e) => toast.error(String(e)),
  });

  if (editing) {
    return (
      <div className="space-y-2">
        {cover.isLoading ? (
          <Skeleton className="h-[72svh] w-full" />
        ) : (
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="min-h-[72svh] font-mono text-sm leading-relaxed"
          />
        )}
        <div className="flex justify-end gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setEditing(false)}
            disabled={save.isPending}
          >
            <X className="size-3.5" /> Cancel
          </Button>
          <Button
            size="sm"
            onClick={() => save.mutate()}
            disabled={!text.trim() || save.isPending}
          >
            {save.isPending ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Save className="size-3.5" />
            )}
            Save & re-render
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex justify-end">
        <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
          <Pencil className="size-3.5" /> Edit text
        </Button>
      </div>
      {coverPdfUrl ? (
        <iframe
          key={reloadKey}
          src={reloadKey ? `${coverPdfUrl}?t=${reloadKey}` : coverPdfUrl}
          className="h-[78svh] w-full rounded-lg border border-border bg-muted"
          title="cover_letter.pdf"
        />
      ) : (
        <p className="text-sm text-muted-foreground">No cover_letter.pdf.</p>
      )}
    </div>
  );
}
