"use client";

import { Plus, X } from "lucide-react";

import { SectionCard } from "./section-card";
import { StringList } from "./string-list";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { MasterResume } from "@/lib/api";

export function SectionSkills({
  value,
  onChange,
}: {
  value: MasterResume;
  onChange: (patch: Partial<MasterResume>) => void;
}) {
  const core = value.core_skills ?? [];
  const adjacent = value.ats_adjacent_skills ?? [];
  // Canonical mapping shape, per PR #57.
  const groups = Object.entries(value.skills ?? {});

  const setGroups = (next: [string, string[]][]) =>
    onChange({ skills: Object.fromEntries(next) });

  return (
    <>
      <SectionCard
        title="Skills you always list"
        why="These appear on every tailored resume, whatever the job asks for."
        summary={`${core.length}`}
      >
        <StringList
          value={core}
          onChange={(core_skills) => onChange({ core_skills })}
          itemLabel="skill"
          placeholder="Python"
        />
      </SectionCard>

      <SectionCard
        title="Skills to add when a job asks"
        why="Only credible neighbours of your real work — added when the posting calls for them."
        summary={`${adjacent.length}`}
      >
        <StringList
          value={adjacent}
          onChange={(ats_adjacent_skills) => onChange({ ats_adjacent_skills })}
          itemLabel="skill"
          placeholder="Docker"
        />
      </SectionCard>

      <SectionCard
        title="Skill groups"
        why="How skills are grouped under headings on the finished resume."
        summary={groups.length === 1 ? "1 group" : `${groups.length} groups`}
      >
        {groups.map(([name, items], index) => (
          <div key={index} className="space-y-2 rounded-lg border border-border p-3">
            <div className="flex items-center gap-2">
              <Label className="sr-only">Group name</Label>
              <Input
                value={name}
                placeholder="languages"
                onChange={(e) => {
                  const next: [string, string[]][] = [...groups];
                  next[index] = [e.target.value, items];
                  setGroups(next);
                }}
                className="max-w-56"
              />
              <div className="flex-1" />
              <Button
                size="icon"
                variant="ghost"
                aria-label="Remove group"
                onClick={() => setGroups(groups.filter((_, i) => i !== index))}
              >
                <X className="size-4" />
              </Button>
            </div>
            <StringList
              value={items}
              onChange={(nextItems) => {
                const next: [string, string[]][] = [...groups];
                next[index] = [name, nextItems];
                setGroups(next);
              }}
              itemLabel="skill"
              placeholder="Python"
            />
          </div>
        ))}
        <Button
          size="sm"
          variant="outline"
          className="gap-1.5"
          onClick={() => setGroups([...groups, ["", []]])}
        >
          <Plus className="size-3.5" /> Add group
        </Button>
      </SectionCard>
    </>
  );
}
