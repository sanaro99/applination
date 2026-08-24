"use client";

/**
 * Chapter 1 — the frame.
 *
 * This chapter is what makes someone willing to talk in chapter 2. It also
 * turns two claims that otherwise live only in the README — never inventing a
 * person, and your files being verifiably yours — into something the user
 * actually sees before being asked for anything.
 */
import Link from "next/link";

import { Button, buttonVariants } from "@/components/ui/button";

import { JourneyShell } from "../journey-shell";

export function ChapterFrame({ onNext }: { onNext: () => void }) {
  return (
    <JourneyShell
      eyebrow="Applination"
      heading="Before we start."
      footerNote={
        <>
          None of this is required. You can skip anything, change everything
          later, and leave whenever you want.
        </>
      }
    >
      <div className="space-y-4 text-base leading-relaxed text-muted-foreground">
        <p>
          I help you find jobs worth applying to, then write the application. To
          do that well I need to know a bit about you.
        </p>
        <p>
          <strong className="text-foreground">
            I will never make anything up about you.
          </strong>{" "}
          Nothing in a document I write will say something you didn&apos;t say
          first.
        </p>
        <p>
          Your files live on this machine, under{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-sm">
            data/users/
          </code>
          . The whole thing is open source — you can read exactly what I do with
          them.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3 pt-2">
        <Button size="lg" onClick={onNext}>
          Start
        </Button>
        <Link href="/" className={buttonVariants({ variant: "ghost" })}>
          Just take me in
        </Link>
      </div>
    </JourneyShell>
  );
}
