"use client";

import { useState } from "react";
import { Briefcase, Check, ChevronsUpDown, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { cn } from "@/lib/utils";
import type { Application } from "@/lib/types";

const CLEAR = "__clear__";

/**
 * Searchable per-conversation job-context picker. Shows the full
 * "Company — Title" label and lets the user re-ground or clear at any time.
 */
export function GroundPicker({
  apps,
  applicationId,
  applicationLabel,
  onChange,
  disabled,
}: {
  apps: Application[];
  applicationId: number | null;
  applicationLabel: string | null;
  onChange: (appId: number | null) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const grounded = applicationId != null;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <Button
            variant={grounded ? "secondary" : "outline"}
            size="sm"
            disabled={disabled}
            className="max-w-[18rem] gap-1.5"
          />
        }
      >
        <Briefcase className="size-3.5 shrink-0" />
        <span className="truncate">
          {grounded ? applicationLabel : "Add job context"}
        </span>
        <ChevronsUpDown className="size-3.5 shrink-0 opacity-50" />
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[22rem] p-0">
        <Command>
          <CommandInput placeholder="Search applications…" />
          <CommandList>
            <CommandEmpty>No applications found.</CommandEmpty>
            {grounded && (
              <CommandItem
                value={CLEAR}
                onSelect={() => {
                  onChange(null);
                  setOpen(false);
                }}
                className="text-muted-foreground"
              >
                <X className="size-3.5" />
                Clear job context
              </CommandItem>
            )}
            {apps.map((a) => {
              const label = `${a.company} — ${a.title}`;
              return (
                <CommandItem
                  key={a.id}
                  value={`${label} ${a.location}`}
                  onSelect={() => {
                    onChange(a.id);
                    setOpen(false);
                  }}
                >
                  <Check
                    className={cn(
                      "size-3.5",
                      a.id === applicationId ? "opacity-100" : "opacity-0",
                    )}
                  />
                  <span className="truncate">{label}</span>
                </CommandItem>
              );
            })}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
