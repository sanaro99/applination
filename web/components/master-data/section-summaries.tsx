"use client";

import { SectionCard } from "./section-card";
import { StringList } from "./string-list";
import type { MasterResume } from "@/lib/api";

export function SectionSummaries({
  value,
  onChange,
}: {
  value: MasterResume;
  onChange: (patch: Partial<MasterResume>) => void;
}) {
  const summaries = value.summary_options ?? [];
  return (
    <SectionCard
      title="How you describe yourself"
      why="One of these is remixed for each job. More options means a closer fit."
      summary={summaries.length === 1 ? "1 version" : `${summaries.length} versions`}
    >
      <StringList
        value={summaries}
        onChange={(summary_options) => onChange({ summary_options })}
        itemLabel="version"
        multiline
        placeholder="Software Engineer with 3+ years building production web services…"
      />
    </SectionCard>
  );
}
