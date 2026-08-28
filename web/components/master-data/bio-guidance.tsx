"use client";

/**
 * What bio.md is for, next to the box you write it in.
 *
 * Deliberately guidance and not fields: this file exists to sound like the
 * person, and a form would produce something that sounds like a form. But an
 * empty textarea labelled "bio.md" tells you nothing about the one job it has —
 * it is pasted into every cover letter prompt as a voice sample the model
 * absorbs and must never reproduce.
 */
import { Quote } from "lucide-react";

const USED_BY = [
  ["Cover letters", "the tone every letter is written in"],
  ["Application questions", "how your answers sound"],
  ["Coach, interviews, essays", "the voice Prepwork replies in"],
] as const;

export function BioGuidance() {
  return (
    <aside className="space-y-4 rounded-xl border border-border p-4 text-sm">
      <div className="flex items-center gap-2 font-medium">
        <Quote className="size-4 text-muted-foreground" />
        What this is for
      </div>

      <p className="text-muted-foreground">
        This is a voice sample, not a summary. It is pasted into the prompt
        every time something is written on your behalf, under the instruction
        &ldquo;absorb the tone, do not reproduce this section&rdquo;. None of it
        is ever copied into a letter.
      </p>

      <ul className="space-y-2">
        {USED_BY.map(([where, what]) => (
          <li key={where} className="text-muted-foreground">
            <span className="font-medium text-foreground">{where}</span> — {what}
          </li>
        ))}
      </ul>

      <div className="space-y-1.5 text-muted-foreground">
        <p className="font-medium text-foreground">Writing it</p>
        <p>
          Write the way you talk, first person, a few paragraphs. What you work
          on, why it interests you, how you approach problems. Facts and
          achievements belong in your resume and stories — those are what the
          letter draws on for content. This decides how it sounds.
        </p>
        <p>
          Roughly the first 1,200 characters reach a cover letter prompt, so put
          the most characteristic writing first.
        </p>
      </div>
    </aside>
  );
}
