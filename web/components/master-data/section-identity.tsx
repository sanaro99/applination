"use client";

import { SectionCard } from "./section-card";
import { StringList } from "./string-list";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import type { MasterProfile, MasterResume } from "@/lib/api";

const LEVELS: MasterProfile["seniority"][] = [
  "student",
  "new-grad",
  "professional",
];

export function SectionIdentity({
  value,
  onChange,
}: {
  value: MasterResume;
  onChange: (patch: Partial<MasterResume>) => void;
}) {
  const profile = value.profile ?? { identity_titles: [], seniority: "professional" };
  const titles = profile.identity_titles ?? [];

  const set = (patch: Partial<MasterProfile>) =>
    onChange({ profile: { ...profile, ...patch } });

  return (
    <SectionCard
      title="Who you are"
      why="Keeps tailored summaries truthful — they never claim a title you don't hold."
      summary={titles.length ? titles[0] : "not set"}
    >
      <div className="space-y-2">
        <Label>Your real job titles</Label>
        <StringList
          value={titles}
          onChange={(identity_titles) => set({ identity_titles })}
          itemLabel="title"
          placeholder="Software Engineer"
        />
      </div>

      <div className="space-y-2">
        <Label>Where you are in your career</Label>
        <Select
          value={profile.seniority}
          onValueChange={(v) => set({ seniority: v as MasterProfile["seniority"] })}
        >
          <SelectTrigger className="w-56">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {LEVELS.map((level) => (
              <SelectItem key={level} value={level}>
                {level}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </SectionCard>
  );
}
