"use client";

/**
 * The control for a story's `tags`, `role_fit` and `company_fit`.
 *
 * These three lists are the highest-leverage text in master data:
 * `reference_loader._score` pays +5 for a tag matching the detected role
 * category and +2 for one overlapping the job description, against +0.25 for a
 * word found in the story body. Typing them by hand into YAML gave that no more
 * weight than the prose it outranks by twentyfold.
 *
 * Suggestions come from the committed `master_data/stories/_INDEX.md`, served
 * by the API — that file says "expand as needed", so free entry stays open. A
 * tag outside the taxonomy is marked rather than refused, because it does cost
 * something real: no +5 role-category bonus, and no credit in the dashboard's
 * story-coverage number.
 */
import { useMemo, useState } from "react";
import { Check, Plus, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import type { TagGroup } from "@/lib/api";

/** The taxonomy writes tags lowercase and hyphenated; typed input follows. */
export function normalizeTag(raw: string): string {
  return raw.trim().toLowerCase().replace(/\s+/g, "-");
}

export function TagPicker({
  value,
  onChange,
  field,
  groups,
  placeholder,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  field: string;
  groups: TagGroup[];
  placeholder: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  // Membership is checked against the whole taxonomy, not just this field's
  // groups: a tag borrowed from another group is still a taxonomy tag, and the
  // dashboard's coverage number counts it as one.
  const known = useMemo(
    () => new Set(groups.flatMap((g) => g.tags)),
    [groups],
  );

  // Suggest only the groups the file says feed this list. Anything else is
  // still typable — it just is not offered, because offering "postgresql" as a
  // `company_fit` would teach the wrong thing about what these lists are.
  const suggested = groups.filter((g) => g.field === field);
  const offTaxonomy = value.filter((t) => !known.has(t));

  const add = (raw: string) => {
    const tag = normalizeTag(raw);
    if (!tag || value.includes(tag)) return;
    onChange([...value, tag]);
    setQuery("");
  };

  const typed = normalizeTag(query);
  const canCreate = typed.length > 0 && !value.includes(typed) && !known.has(typed);

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        {value.map((tag) => (
          <Badge
            key={tag}
            variant={known.has(tag) ? "secondary" : "outline"}
            className={cn(
              "gap-1 py-1 pl-2.5 pr-1",
              !known.has(tag) && "border-dashed text-muted-foreground",
            )}
          >
            {tag}
            <button
              type="button"
              onClick={() => onChange(value.filter((t) => t !== tag))}
              className="ml-0.5 rounded-full p-0.5 hover:bg-muted-foreground/20"
              aria-label={`Remove ${tag}`}
            >
              <X className="size-3" />
            </button>
          </Badge>
        ))}

        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger
            render={<Button variant="outline" size="sm" className="h-7 gap-1" />}
          >
            <Plus className="size-3.5" /> Add
          </PopoverTrigger>
          <PopoverContent align="start" className="w-72 p-0">
            <Command>
              <CommandInput
                value={query}
                onValueChange={setQuery}
                placeholder={placeholder}
              />
              <CommandList>
                <CommandEmpty>Type a tag and press Enter to add it.</CommandEmpty>
                {canCreate && (
                  <CommandGroup heading="Not in the taxonomy">
                    <CommandItem value={typed} onSelect={() => add(typed)}>
                      <Plus className="size-3.5" />
                      Add &ldquo;{typed}&rdquo;
                    </CommandItem>
                  </CommandGroup>
                )}
                {suggested.map((group) => (
                  <CommandGroup key={group.label} heading={group.label}>
                    {group.tags.map((tag) => (
                      <CommandItem key={tag} value={tag} onSelect={() => add(tag)}>
                        <Check
                          className={cn(
                            "size-3.5",
                            value.includes(tag) ? "opacity-100" : "opacity-0",
                          )}
                        />
                        {tag}
                      </CommandItem>
                    ))}
                  </CommandGroup>
                ))}
              </CommandList>
            </Command>
          </PopoverContent>
        </Popover>
      </div>

      {offTaxonomy.length > 0 && (
        <p className="text-xs text-muted-foreground">
          <span className="font-medium">{offTaxonomy.join(", ")}</span>{" "}
          {offTaxonomy.length === 1 ? "is" : "are"} outside the shared taxonomy.
          Still matched word-for-word against a job description, but no
          role-category bonus and no credit towards story coverage.
        </p>
      )}
    </div>
  );
}
