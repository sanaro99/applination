"use client";

/**
 * The journey: six chapters, one question each, then the dashboard.
 *
 * A thin router on purpose. The old file held seven step components in 795
 * lines, which is well past the size where edits are reliable; each chapter now
 * owns its own copy, state and requests, and this file only decides which one
 * is on screen.
 *
 * The fingerprint stays pinned while chapters change, because it is the one
 * thing being built — the chapters are the means, not the object.
 */
import { useQuery } from "@tanstack/react-query";

import { Fingerprint } from "@/components/onboarding/fingerprint";
import { useJourneyStore } from "@/components/onboarding/use-journey-store";
import { ChapterFrame } from "@/components/onboarding/chapters/01-frame";
import { ChapterTalk } from "@/components/onboarding/chapters/02-talk";
import { ChapterThread } from "@/components/onboarding/chapters/03-thread";
import { ChapterSearch } from "@/components/onboarding/chapters/04-search";
import { ChapterPayoff } from "@/components/onboarding/chapters/05-payoff";
import { ChapterIgnition } from "@/components/onboarding/chapters/06-ignition";
import { api } from "@/lib/api";

const LAST = 5;

export default function OnboardingPage() {
  const chapter = useJourneyStore((s) => s.chapter);
  const setChapter = useJourneyStore((s) => s.setChapter);

  const { data: strength } = useQuery({
    queryKey: ["profile-strength"],
    queryFn: () => api.profileStrength(),
    retry: false,
  });

  const next = () => setChapter(Math.min(chapter + 1, LAST));
  const back = () => setChapter(Math.max(chapter - 1, 0));

  return (
    <div className="relative flex min-h-svh flex-col">
      <div className="pointer-events-none absolute right-6 top-6 z-10">
        <Fingerprint
          ridges={strength?.ridges ?? []}
          filled={strength?.filled ?? 0}
          total={strength?.total ?? 9}
          size={96}
        />
      </div>

      {chapter === 0 && <ChapterFrame onNext={next} />}
      {chapter === 1 && <ChapterTalk onNext={next} onBack={back} />}
      {chapter === 2 && <ChapterThread onNext={next} onBack={back} />}
      {chapter === 3 && <ChapterSearch onNext={next} onBack={back} />}
      {chapter === 4 && <ChapterPayoff onNext={next} onBack={back} />}
      {chapter === 5 && <ChapterIgnition onBack={back} />}
    </div>
  );
}
