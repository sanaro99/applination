"use client";

import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  FileText,
  Gauge,
  LayoutDashboard,
  Library,
  ListChecks,
  Play,
  Settings,
} from "lucide-react";

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { useUI } from "@/lib/store";
import { api } from "@/lib/api";

export function CommandPalette() {
  const { commandOpen, setCommandOpen } = useUI();
  const router = useRouter();
  const { data: apps } = useQuery({
    queryKey: ["applications", "palette"],
    queryFn: () => api.listApplications(),
    enabled: commandOpen,
  });

  const go = (href: string) => {
    setCommandOpen(false);
    router.push(href);
  };

  return (
    <CommandDialog
      open={commandOpen}
      onOpenChange={setCommandOpen}
      title="Command palette"
      description="Navigate, run, search."
    >
      <CommandInput placeholder="Type a command or search applications…" />
      <CommandList>
        <CommandEmpty>No results.</CommandEmpty>
        <CommandGroup heading="Navigate">
          <CommandItem onSelect={() => go("/")}>
            <LayoutDashboard className="size-4" /> Dashboard
          </CommandItem>
          <CommandItem onSelect={() => go("/run")}>
            <Play className="size-4" /> Run pipeline
          </CommandItem>
          <CommandItem onSelect={() => go("/applications")}>
            <ListChecks className="size-4" /> Applications
          </CommandItem>
          <CommandItem onSelect={() => go("/single")}>
            <FileText className="size-4" /> Single job
          </CommandItem>
          <CommandItem onSelect={() => go("/runs")}>
            <Activity className="size-4" /> Run history
          </CommandItem>
          <CommandItem onSelect={() => go("/config")}>
            <Settings className="size-4" /> Config
          </CommandItem>
          <CommandItem onSelect={() => go("/master-data")}>
            <Library className="size-4" /> Master data
          </CommandItem>
          <CommandItem onSelect={() => go("/stats")}>
            <Gauge className="size-4" /> Stats
          </CommandItem>
        </CommandGroup>
        {apps && apps.length > 0 && (
          <>
            <CommandSeparator />
            <CommandGroup heading="Applications">
              {apps.slice(0, 30).map((app) => (
                <CommandItem
                  key={app.id}
                  value={`${app.company} ${app.title}`}
                  onSelect={() => go(`/applications/${app.id}`)}
                >
                  <span className="font-medium">{app.company}</span>
                  <span className="text-muted-foreground">— {app.title}</span>
                  <span className="ml-auto text-xs text-muted-foreground">
                    {app.match_score}
                  </span>
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}
      </CommandList>
    </CommandDialog>
  );
}
