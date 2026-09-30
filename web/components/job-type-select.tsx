"use client";

import { useId } from "react";
import { Label } from "@/components/ui/label";
import { JOB_TYPE_OPTIONS, type JobType } from "@/lib/job-types";

export function JobTypeSelect({
  value,
  onChange,
}: {
  value: JobType;
  onChange: (value: JobType) => void;
}) {
  const id = useId();
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>Job type</Label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value as JobType)}
        className="h-9 w-full max-w-sm rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {JOB_TYPE_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
      <p className="text-xs text-muted-foreground">
        Choose the kind of position you want. “Use role keywords” infers it from
        your search terms. You can keep “new grad” in your role keywords.
      </p>
    </div>
  );
}
