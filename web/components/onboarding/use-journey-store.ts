"use client";

/**
 * In-flight journey state.
 *
 * Persisted to localStorage because a user who dictates for ninety seconds and
 * loses it to a reload will not do it twice. This is belt-and-braces: each
 * chapter also autosaves to the server, which is what actually survives a
 * different browser.
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";

export type JourneyState = {
  chapter: number;
  notes: string;
  /** Titles of stories already told this session, for the "one more?" copy. */
  toldStories: string[];
  keywords: string[];
  /** Which chapters were filled from the sample, so we can mark them. */
  sampleUsed: string[];
  setChapter: (n: number) => void;
  setNotes: (s: string) => void;
  addToldStory: (title: string) => void;
  setKeywords: (k: string[]) => void;
  markSample: (chapter: string) => void;
  reset: () => void;
};

export const useJourneyStore = create<JourneyState>()(
  persist(
    (set) => ({
      chapter: 0,
      notes: "",
      toldStories: [],
      keywords: [],
      sampleUsed: [],
      setChapter: (n) => set({ chapter: n }),
      setNotes: (s) => set({ notes: s }),
      addToldStory: (title) =>
        set((s) => ({ toldStories: [...s.toldStories, title] })),
      setKeywords: (k) => set({ keywords: k }),
      markSample: (chapter) =>
        set((s) =>
          s.sampleUsed.includes(chapter)
            ? s
            : { sampleUsed: [...s.sampleUsed, chapter] },
        ),
      reset: () =>
        set({
          chapter: 0,
          notes: "",
          toldStories: [],
          keywords: [],
          sampleUsed: [],
        }),
    }),
    { name: "applination.journey.v1" },
  ),
);
