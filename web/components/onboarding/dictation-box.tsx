"use client";

/**
 * A big, forgiving input sized for spoken-length answers.
 *
 * There is no microphone here on purpose. Voice arrives through the user's own
 * dictation tool (Wispr Flow, a phone keyboard mic, OS dictation) writing into
 * this textarea — which keeps every browser working, keeps audio off third
 * parties, and lets the privacy promise in chapter 1 stay literally true.
 *
 * "They paused" is therefore just a debounce on input, and behaves identically
 * whether the user typed or dictated.
 */
import { useEffect, useRef } from "react";

import { Textarea } from "@/components/ui/textarea";

const SETTLE_MS = 1200;

export function DictationBox({
  value,
  onChange,
  onSettled,
  placeholder,
  minRows = 6,
}: {
  value: string;
  onChange: (s: string) => void;
  onSettled?: (s: string) => void;
  placeholder?: string;
  minRows?: number;
}) {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Held in a ref so an inline callback prop does not restart the debounce on
  // every render — which would mean it never fires while the user is typing.
  // Written in an effect, not during render: a ref mutated mid-render can be
  // torn by a re-entrant render.
  const settled = useRef(onSettled);
  useEffect(() => {
    settled.current = onSettled;
  }, [onSettled]);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    if (!value.trim()) return;
    timer.current = setTimeout(() => settled.current?.(value), SETTLE_MS);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [value]);

  return (
    <Textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      rows={minRows}
      className="min-h-40 text-base leading-relaxed"
    />
  );
}
