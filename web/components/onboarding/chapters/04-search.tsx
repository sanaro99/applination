"use client";

/**
 * Chapter 4 — "here's what I think you're for".
 *
 * The assistant proposes and the user corrects; they never fill in a job-search
 * form. When the extraction had little to work from it says so rather than
 * presenting a guess with confidence it has not earned.
 *
 * Settling this chapter kicks off the LLM-free scrape behind chapter 5, so the
 * count is usually ready by the time the user arrives.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { SAMPLE } from "@/lib/sample-data";

import { JourneyShell } from "../journey-shell";
import { useJourneyStore } from "../use-journey-store";

export function ChapterSearch({
  onNext,
  onBack,
}: {
  onNext: () => void;
  onBack: () => void;
}) {
  const qc = useQueryClient();
  const keywords = useJourneyStore((s) => s.keywords);
  const setKeywords = useJourneyStore((s) => s.setKeywords);
  const markSample = useJourneyStore((s) => s.markSample);
  const [draft, setDraft] = useState("");
  // Distinguishes "hasn't touched the chips yet" from "deliberately cleared
  // them" — without it, deleting the last chip falls back to the extraction and
  // the chip the user just removed reappears.
  const [touched, setTouched] = useState(false);

  const { data } = useQuery({
    queryKey: ["intake-search-terms"],
    queryFn: () => api.intakeSearchTerms(),
    retry: false,
  });

  // The extraction is only a fallback for display. Nothing is copied into the
  // store until the user actually edits, so a correction is never undone by a
  // refetch, and an empty store means "not touched yet" rather than "cleared".
  const shown =
    touched || keywords.length ? keywords : (data?.keywords ?? []);
  const guessed = data?.guessed ?? true;

  const save = useMutation({
    mutationFn: async (terms: string[]) => {
      await api.setOnboardingSearch({ keywords: terms });
      // Fire the scrape before advancing so it overlaps the transition.
      await api.startJobPreview();
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["profile-strength"] });
      void qc.invalidateQueries({ queryKey: ["onboarding-status"] });
      onNext();
    },
    onError: (e) => toast.error(String(e)),
  });

  const add = () => {
    const value = draft.trim();
    if (!value || shown.includes(value)) {
      setDraft("");
      return;
    }
    setTouched(true);
    setKeywords([...shown, value]);
    setDraft("");
  };

  return (
    <JourneyShell
      eyebrow="Chapter 4"
      heading={
        guessed
          ? "I don't have much to go on yet — is this close?"
          : "Here's what I think you're for."
      }
      onBack={onBack}
      onNext={() => save.mutate(shown)}
      onSkip={onNext}
      onSample={() => {
        setTouched(true);
        setKeywords([...SAMPLE.keywords]);
        markSample("search");
        void api
          .markSampleUsed()
          .then(() => qc.invalidateQueries({ queryKey: ["onboarding-status"] }))
          .catch(() => {});
      }}
      busy={save.isPending}
    >
      <p className="text-sm text-muted-foreground">
        {guessed
          ? "I'm guessing here. Change anything."
          : "This is what I'd go looking for. Change anything that's wrong."}
      </p>

      <div className="flex flex-wrap gap-2">
        {shown.map((k) => (
          <span
            key={k}
            className="inline-flex items-center gap-1.5 rounded-full border border-border px-3 py-1.5 text-sm"
          >
            {k}
            <button
              onClick={() => {
                setTouched(true);
                setKeywords(shown.filter((x) => x !== k));
              }}
              aria-label={`Remove ${k}`}
              className="text-muted-foreground transition-colors hover:text-destructive"
            >
              <X className="size-3.5" />
            </button>
          </span>
        ))}
        {shown.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Nothing yet — add whatever you&apos;d type into a job board.
          </p>
        ) : null}
      </div>

      <div className="flex max-w-md gap-2">
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          placeholder="Add a role or a technology"
        />
        <Button variant="outline" onClick={add}>
          Add
        </Button>
      </div>
    </JourneyShell>
  );
}
