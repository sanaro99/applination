"use client";

/**
 * One chapter, full-bleed.
 *
 * Deliberately not a chat thread: the journey runs before the user has an API
 * key, so there is no model behind it. A scripted state machine wearing a chat
 * costume gets noticed within three turns and costs more trust than the old
 * wizard ever did. This frame is honest about being considered copy.
 */
import { ArrowLeft, ArrowRight, Loader2 } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";

export function JourneyShell({
  eyebrow,
  heading,
  children,
  onBack,
  onNext,
  onSkip,
  onSample,
  nextLabel = "Continue",
  busy = false,
  footerNote,
}: {
  eyebrow?: string;
  heading: string;
  children: ReactNode;
  onBack?: () => void;
  onNext?: () => void;
  onSkip?: () => void;
  onSample?: () => void;
  nextLabel?: string;
  busy?: boolean;
  footerNote?: ReactNode;
}) {
  return (
    <section className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center gap-6 px-6 py-10">
      <header className="space-y-2">
        {eyebrow ? (
          <p className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
            {eyebrow}
          </p>
        ) : null}
        <h1 className="font-heading text-3xl font-extrabold tracking-tight sm:text-4xl">
          {heading}
        </h1>
      </header>

      <div className="space-y-4">{children}</div>

      {footerNote ? (
        <p className="text-xs text-muted-foreground">{footerNote}</p>
      ) : null}

      <footer className="flex flex-wrap items-center gap-2 pt-2">
        {onBack ? (
          <Button variant="ghost" onClick={onBack} className="gap-2">
            <ArrowLeft className="size-4" /> Back
          </Button>
        ) : null}
        <div className="flex-1" />
        {onSample ? (
          <Button variant="ghost" size="sm" onClick={onSample}>
            Use a sample
          </Button>
        ) : null}
        {onSkip ? (
          <Button variant="ghost" size="sm" onClick={onSkip}>
            Skip this
          </Button>
        ) : null}
        {onNext ? (
          <Button onClick={onNext} disabled={busy} className="gap-2">
            {busy ? <Loader2 className="size-4 animate-spin" /> : null}
            {nextLabel} <ArrowRight className="size-4" />
          </Button>
        ) : null}
      </footer>
    </section>
  );
}
