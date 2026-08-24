"use client";

/**
 * Chapter 3 — follow the thread.
 *
 * The chips are the user's own words, extracted deterministically. Letting them
 * pick the thread is what removes the need for a model: with no key we cannot
 * generate an intelligent follow-up, but we do not have to — being asked about
 * the specific thing you just mentioned reads as listening, not as guessing.
 *
 * The questions are in a friend's register on purpose. "Tell me about something
 * you're proud of" returns the rehearsed LinkedIn version, which is useless as
 * raw material; "what was the annoying part" returns specifics and judgement,
 * which is what stops generated prose sounding generated.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { SAMPLE } from "@/lib/sample-data";
import { cn } from "@/lib/utils";

import { DictationBox } from "../dictation-box";
import { JourneyShell } from "../journey-shell";
import { useJourneyStore } from "../use-journey-store";

const SOMETHING_ELSE = "Something else";

export function ChapterThread({
  onNext,
  onBack,
}: {
  onNext: () => void;
  onBack: () => void;
}) {
  const qc = useQueryClient();
  const toldStories = useJourneyStore((s) => s.toldStories);
  const addToldStory = useJourneyStore((s) => s.addToldStory);
  const markSample = useJourneyStore((s) => s.markSample);

  const [picked, setPicked] = useState<string | null>(null);
  const [customLabel, setCustomLabel] = useState("");
  const [body, setBody] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["intake-threads"],
    queryFn: () => api.intakeThreads(),
    retry: false,
  });
  const threads = data?.threads ?? [];
  // With nothing extracted there is no menu to offer, so ask the open question
  // rather than showing a chip row containing only "Something else".
  const bare = !isLoading && threads.length === 0;

  const save = useMutation({
    mutationFn: ({ title, text }: { title: string; text: string }) =>
      api.saveIntakeStory(title, text),
    onSuccess: (_res, vars) => {
      addToldStory(vars.title);
      setPicked(null);
      setCustomLabel("");
      setBody("");
      void qc.invalidateQueries({ queryKey: ["profile-strength"] });
      void qc.invalidateQueries({ queryKey: ["onboarding-status"] });
      void qc.invalidateQueries({ queryKey: ["intake-threads"] });
    },
    onError: (e) => toast.error(String(e)),
  });

  const label =
    picked === SOMETHING_ELSE ? customLabel.trim() || "Something else" : picked;

  const useSample = () => {
    save.mutate({ title: SAMPLE.story.title, text: SAMPLE.story.body });
    markSample("thread");
    void api
      .markSampleUsed()
      .then(() => qc.invalidateQueries({ queryKey: ["onboarding-status"] }))
      .catch(() => {});
  };

  const telling = picked !== null || bare;

  return (
    <JourneyShell
      eyebrow="Chapter 3"
      heading={
        telling && label
          ? `${label} — what were you actually doing there?`
          : bare
            ? "Tell me about one thing you worked on."
            : toldStories.length
              ? "Anything else you want to tell me about?"
              : "Which of these do you want to tell me about?"
      }
      onBack={onBack}
      onSample={useSample}
      onSkip={onNext}
      onNext={
        telling
          ? () =>
              body.trim() &&
              save.mutate({ title: label || "Something else", text: body })
          : onNext
      }
      nextLabel={telling ? "Save this" : "Continue"}
      busy={save.isPending}
      footerNote={
        toldStories.length
          ? `Saved so far: ${toldStories.join(", ")}.`
          : "Skip any of this — you can add stories later from Master data."
      }
    >
      {telling ? (
        <>
          {picked === SOMETHING_ELSE ? (
            <Input
              value={customLabel}
              onChange={(e) => setCustomLabel(e.target.value)}
              placeholder="What should I call it?"
              className="max-w-sm"
            />
          ) : null}
          <DictationBox
            value={body}
            onChange={setBody}
            placeholder="How it went, what was annoying, what you'd do differently."
          />
          {!bare ? (
            <Button variant="ghost" size="sm" onClick={() => setPicked(null)}>
              Pick something else
            </Button>
          ) : null}
        </>
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            {[...threads.map((t) => t.label), SOMETHING_ELSE].map((name) => (
              <button
                key={name}
                onClick={() => setPicked(name)}
                className={cn(
                  "rounded-full border border-border px-3 py-1.5 text-sm transition-colors",
                  "hover:border-primary hover:bg-primary/10 hover:text-primary",
                  toldStories.includes(name) &&
                    "border-primary/40 text-muted-foreground",
                )}
              >
                {name}
              </button>
            ))}
          </div>
          {isLoading ? (
            <p className="text-sm text-muted-foreground">
              Looking at what you just told me…
            </p>
          ) : null}
          {toldStories.length ? (
            <Button variant="ghost" size="sm" onClick={onNext}>
              That&apos;s enough for now
            </Button>
          ) : null}
        </>
      )}
    </JourneyShell>
  );
}
