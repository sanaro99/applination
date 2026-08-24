"use client";

/**
 * Chapter 2 — just talk.
 *
 * One question, one large forgiving box. No fields, no validation, no length
 * requirement: this chapter has to be easier to answer than it is to skip,
 * because everything downstream is built from whatever it produces.
 *
 * The resume is offered as a shortcut *inside* the conversation, and only its
 * text is parked — turning it into structured data needs a model, which the
 * user does not have yet.
 */
import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Upload } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { SAMPLE } from "@/lib/sample-data";

import { DictationBox } from "../dictation-box";
import { JourneyShell } from "../journey-shell";
import { useJourneyStore } from "../use-journey-store";

export function ChapterTalk({
  onNext,
  onBack,
}: {
  onNext: () => void;
  onBack: () => void;
}) {
  const qc = useQueryClient();
  const notes = useJourneyStore((s) => s.notes);
  const setNotes = useJourneyStore((s) => s.setNotes);
  const markSample = useJourneyStore((s) => s.markSample);
  const [parkedChars, setParkedChars] = useState<number | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const refreshStrength = () => {
    void qc.invalidateQueries({ queryKey: ["profile-strength"] });
    void qc.invalidateQueries({ queryKey: ["onboarding-status"] });
  };

  const saveNotes = useMutation({
    mutationFn: (text: string) => api.saveIntakeNotes(text),
    onSuccess: refreshStrength,
    onError: (e) => toast.error(String(e)),
  });

  const parkResume = useMutation({
    mutationFn: (file: File) => api.parkIntakeResume(file),
    onSuccess: (res) => {
      setParkedChars(res.chars);
      refreshStrength();
    },
    onError: (e) => toast.error(String(e)),
  });

  const useSample = () => {
    setNotes(SAMPLE.notes);
    saveNotes.mutate(SAMPLE.notes);
    markSample("talk");
    void api.markSampleUsed().then(refreshStrength).catch(() => {});
  };

  const advance = () => {
    if (notes.trim()) saveNotes.mutate(notes);
    onNext();
  };

  return (
    <JourneyShell
      eyebrow="Chapter 2"
      heading="So — what have you been working on lately?"
      onBack={onBack}
      onNext={advance}
      onSkip={onNext}
      onSample={useSample}
      busy={saveNotes.isPending}
    >
      <DictationBox
        value={notes}
        onChange={setNotes}
        onSettled={(text) => saveNotes.mutate(text)}
        placeholder="Whatever comes to mind. Ramble if you like — nobody's marking this."
      />
      <p className="text-sm text-muted-foreground">
        Talking is easier than typing. If you have a dictation tool — Wispr Flow,
        or your phone&apos;s keyboard mic — use it.
      </p>

      <div className="rounded-lg border border-dashed border-border p-4">
        <p className="text-sm text-muted-foreground">
          Or drop your resume and I&apos;ll read it instead of making you type.
        </p>
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,.docx,.txt,.md"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) parkResume.mutate(file);
            e.target.value = "";
          }}
        />
        <Button
          variant="outline"
          size="sm"
          className="mt-3 gap-2"
          onClick={() => fileRef.current?.click()}
          disabled={parkResume.isPending}
        >
          {parkResume.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Upload className="size-4" />
          )}
          Choose a file
        </Button>
        {parkedChars !== null ? (
          <p className="mt-3 text-sm text-foreground">
            Got it — that&apos;s {parkedChars.toLocaleString()} characters of
            resume parked. I&apos;ll turn it into something structured once you
            connect a provider.
          </p>
        ) : null}
      </div>
    </JourneyShell>
  );
}
