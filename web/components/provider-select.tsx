"use client";

import { useQuery } from "@tanstack/react-query";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api";

const DEFAULT = "__default__";

/**
 * Picks an LLM provider for a one-off action. The "Use default" option leaves
 * the choice to the configured task chain (value === null).
 */
export function ProviderSelect({
  value,
  onChange,
  className,
  includeDefault = true,
}: {
  value: string | null;
  onChange: (provider: string | null) => void;
  className?: string;
  includeDefault?: boolean;
}) {
  const { data } = useQuery({
    queryKey: ["providers"],
    queryFn: () => api.listProviders(),
  });
  return (
    <Select
      value={value ?? (includeDefault ? DEFAULT : "")}
      onValueChange={(v) => onChange(v === DEFAULT ? null : v)}
    >
      <SelectTrigger className={className}>
        <SelectValue placeholder="Provider…" />
      </SelectTrigger>
      <SelectContent>
        {includeDefault && (
          <SelectItem value={DEFAULT}>Use default</SelectItem>
        )}
        {(data ?? []).map((p) => (
          <SelectItem key={p.name} value={p.name} disabled={!p.configured}>
            {p.name}
            {p.configured ? "" : " (no key)"}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
