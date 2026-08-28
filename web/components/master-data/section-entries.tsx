"use client";

/**
 * Jobs, projects and education.
 *
 * One component for three sections because they are the same shape — a list of
 * records with a few fields, two of which also carry a bullet pool. Three
 * near-identical components would drift the moment one gained a field.
 */
import {
  DndContext,
  closestCenter,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Plus, X } from "lucide-react";

import { SectionCard } from "./section-card";
import { StringList } from "./string-list";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { MasterResume } from "@/lib/api";

type Kind = "experience" | "projects" | "education";
type Entry = Record<string, unknown>;

const FIELDS: Record<Kind, { key: string; label: string; placeholder?: string }[]> = {
  experience: [
    { key: "company", label: "Company", placeholder: "Example Corp" },
    { key: "role", label: "Job title", placeholder: "Software Engineer" },
    { key: "location", label: "Location", placeholder: "City, ST" },
    { key: "start_date", label: "Started", placeholder: "Jun 2022" },
    { key: "end_date", label: "Ended", placeholder: "Present" },
  ],
  projects: [
    { key: "name", label: "Project name", placeholder: "Applination" },
    { key: "tech", label: "Built with", placeholder: "Python, FastAPI" },
    { key: "link", label: "Link", placeholder: "https://…" },
  ],
  education: [
    { key: "school", label: "School", placeholder: "State University" },
    { key: "degree", label: "Degree", placeholder: "BS Computer Science" },
    { key: "location", label: "Location", placeholder: "City, ST" },
    { key: "start_date", label: "Started", placeholder: "Sep 2018" },
    { key: "end_date", label: "Ended", placeholder: "May 2022" },
    { key: "gpa", label: "GPA", placeholder: "3.8" },
  ],
};

const COPY: Record<Kind, { title: string; why: string; noun: string }> = {
  experience: {
    title: "Jobs you've had",
    why: "List every real bullet — the tailor picks the best ones for each job.",
    noun: "job",
  },
  projects: {
    title: "Projects",
    why: "Things you built that a posting might care about.",
    noun: "project",
  },
  education: {
    title: "Education",
    why: "Used to work out how your experience should be positioned.",
    noun: "school",
  },
};

const HAS_BULLETS: Record<Kind, boolean> = {
  experience: true,
  projects: true,
  education: false,
};

function label(kind: Kind, entry: Entry): string {
  if (kind === "projects") return String(entry.name || "Untitled project");
  if (kind === "education") return String(entry.school || "Untitled");
  return [entry.role, entry.company].filter(Boolean).join(" @ ") || "Untitled job";
}

export function SectionEntries({
  kind,
  value,
  onChange,
}: {
  kind: Kind;
  value: MasterResume;
  onChange: (patch: Partial<MasterResume>) => void;
}) {
  const entries = ((value[kind] ?? []) as unknown as Entry[]) ?? [];
  const ids = entries.map((_, i) => `${kind}-${i}`);
  const copy = COPY[kind];

  const commit = (next: Entry[]) =>
    onChange({ [kind]: next } as unknown as Partial<MasterResume>);

  const onDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    commit(arrayMove(entries, ids.indexOf(String(active.id)), ids.indexOf(String(over.id))));
  };

  const blank: Entry = HAS_BULLETS[kind] ? { bullets_all: [] } : {};

  return (
    <SectionCard
      title={copy.title}
      why={copy.why}
      summary={entries.length === 1 ? `1 ${copy.noun}` : `${entries.length} ${copy.noun}s`}
    >
      <DndContext collisionDetection={closestCenter} onDragEnd={onDragEnd}>
        <SortableContext items={ids} strategy={verticalListSortingStrategy}>
          {entries.map((entry, index) => (
            <EntryCard
              key={ids[index]}
              id={ids[index]}
              kind={kind}
              entry={entry}
              heading={label(kind, entry)}
              onChange={(next) =>
                commit(entries.map((e, i) => (i === index ? next : e)))
              }
              onRemove={() => commit(entries.filter((_, i) => i !== index))}
            />
          ))}
        </SortableContext>
      </DndContext>

      <Button
        size="sm"
        variant="outline"
        className="gap-1.5"
        onClick={() => commit([...entries, blank])}
      >
        <Plus className="size-3.5" /> Add {copy.noun}
      </Button>
    </SectionCard>
  );
}

function EntryCard({
  id,
  kind,
  entry,
  heading,
  onChange,
  onRemove,
}: {
  id: string;
  kind: Kind;
  entry: Entry;
  heading: string;
  onChange: (next: Entry) => void;
  onRemove: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition } =
    useSortable({ id });

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className="space-y-3 rounded-lg border border-border p-3"
    >
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="cursor-grab text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="Reorder"
          {...attributes}
          {...listeners}
        >
          <GripVertical className="size-4" />
        </button>
        <span className="flex-1 text-sm font-medium">{heading}</span>
        <Button size="icon" variant="ghost" aria-label="Remove" onClick={onRemove}>
          <X className="size-4" />
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {FIELDS[kind].map((field) => (
          <div key={field.key} className="grid gap-1.5">
            <Label htmlFor={`${id}-${field.key}`}>{field.label}</Label>
            <Input
              id={`${id}-${field.key}`}
              value={String(entry[field.key] ?? "")}
              placeholder={field.placeholder}
              onChange={(e) => onChange({ ...entry, [field.key]: e.target.value })}
            />
          </div>
        ))}
      </div>

      {HAS_BULLETS[kind] ? (
        <div className="space-y-2">
          <Label>What you did</Label>
          <StringList
            value={(entry.bullets_all as string[]) ?? []}
            onChange={(bullets_all) => onChange({ ...entry, bullets_all })}
            itemLabel="bullet"
            multiline
            placeholder="Built X using Y, cutting Z by N%."
          />
        </div>
      ) : null}
    </div>
  );
}
