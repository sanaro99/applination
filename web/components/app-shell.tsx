"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  CircleSlash,
  Command,
  FileText,
  Gauge,
  LayoutDashboard,
  Library,
  ListChecks,
  Loader2,
  MessageSquare,
  Mic,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  PenLine,
  Play,
  Route,
  Settings,
  Sun,
  Zap,
} from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import { useLatestRuns } from "@/lib/use-latest-runs";
import { useUI, readStoredSidebarCollapsed } from "@/lib/store";
import { CommandPalette } from "@/components/command-palette";
import { RunActivityWatcher } from "@/components/run-activity-watcher";
import { OnboardingGate } from "@/components/onboarding-gate";

interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

interface NavSection {
  label: string;
  items: NavItem[];
}

const navSections: NavSection[] = [
  {
    label: "Workspace",
    items: [
      { href: "/", label: "Dashboard", icon: LayoutDashboard },
      { href: "/run", label: "Run pipeline", icon: Play },
      { href: "/applications", label: "Applications", icon: ListChecks },
      { href: "/single", label: "Single job", icon: FileText },
    ],
  },
  {
    label: "Prepwork",
    items: [
      { href: "/coach", label: "Coach", icon: MessageSquare },
      { href: "/interview", label: "Mock interview", icon: Mic },
      { href: "/essay", label: "Essay drafter", icon: PenLine },
    ],
  },
  {
    label: "Insights",
    items: [
      { href: "/runs", label: "Run history", icon: Activity },
      { href: "/stats", label: "Stats", icon: Gauge },
    ],
  },
  {
    label: "Setup",
    items: [
      { href: "/config", label: "Config", icon: Settings },
      { href: "/workflows", label: "Workflows", icon: Route },
      { href: "/master-data", label: "Master data", icon: Library },
    ],
  },
];

function titleCase(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

const PAGE_TITLES: { match: (p: string) => boolean; title: string }[] = [
  { match: (p) => p === "/", title: "Dashboard" },
  { match: (p) => p.startsWith("/run") && !p.startsWith("/runs"), title: "Run pipeline" },
  { match: (p) => p.startsWith("/applications"), title: "Applications" },
  { match: (p) => p.startsWith("/single"), title: "Single job" },
  { match: (p) => p.startsWith("/coach"), title: "Coach" },
  { match: (p) => p.startsWith("/interview"), title: "Mock interview" },
  { match: (p) => p.startsWith("/essay"), title: "Essay drafter" },
  { match: (p) => p.startsWith("/runs"), title: "Run history" },
  { match: (p) => p.startsWith("/config"), title: "Config" },
  { match: (p) => p.startsWith("/workflows"), title: "Workflows" },
  { match: (p) => p.startsWith("/master-data"), title: "Master data" },
  { match: (p) => p.startsWith("/stats"), title: "Stats" },
];

function PageTitle() {
  const pathname = usePathname() ?? "/";
  const title = PAGE_TITLES.find((t) => t.match(pathname))?.title ?? "Applination";
  return (
    <h1 className="font-heading text-base font-semibold tracking-tight">
      {title}
    </h1>
  );
}

function RunStatusPill() {
  const { data, isLoading } = useLatestRuns();
  if (isLoading) {
    return (
      <Badge variant="outline" className="gap-2">
        <Loader2 className="size-3 animate-spin" /> Loading
      </Badge>
    );
  }
  const latest = data?.[0];
  if (!latest) {
    return (
      <Badge variant="outline" className="gap-2 text-muted-foreground">
        <CircleSlash className="size-3" /> No runs yet
      </Badge>
    );
  }
  const variant: "default" | "secondary" | "destructive" | "outline" =
    latest.status === "running"
      ? "default"
      : latest.status === "error"
        ? "destructive"
        : latest.status === "done"
          ? "secondary"
          : "outline";
  const icon =
    latest.status === "running" ? (
      <Loader2 className="size-3 animate-spin" />
    ) : latest.status === "done" ? (
      <Zap className="size-3" />
    ) : latest.status === "error" || latest.status === "cancelled" ? (
      <CircleSlash className="size-3" />
    ) : (
      <Loader2 className="size-3" />
    );
  return (
    <Link href={`/runs/${latest.id}`}>
      <Badge variant={variant} className="gap-2 cursor-pointer">
        {icon}
        Run #{latest.id} · {titleCase(latest.status)}
      </Badge>
    </Link>
  );
}

function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label="Toggle theme"
      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
    >
      <Sun className="size-4 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
      <Moon className="absolute size-4 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
    </Button>
  );
}

function Sidebar() {
  const pathname = usePathname();
  const { sidebarCollapsed: collapsed, toggleSidebar } = useUI();

  // When expanded, the sidebar keeps its responsive behaviour (icon rail on
  // mobile, full width on md+). When collapsed it is forced to the icon rail at
  // every breakpoint, and all text is hidden — only icons remain.
  const labelCls = collapsed ? "hidden" : "hidden md:inline";

  return (
    <aside
      className={cn(
        "surface-grain sticky top-0 z-40 flex h-svh w-[68px] shrink-0 flex-col border-r border-sidebar-border bg-sidebar/85 backdrop-blur-xl transition-[width] duration-200",
        !collapsed && "md:w-[264px]",
      )}
    >
      <div
        className={cn(
          "flex h-14 shrink-0 items-center justify-center gap-2.5 border-b border-sidebar-border px-4",
          !collapsed && "md:justify-start",
        )}
      >
        <span className="brand-gradient flex size-8 shrink-0 items-center justify-center rounded-lg shadow-lg shadow-primary/25 ring-1 ring-white/20">
          <Zap className="size-4 text-white" strokeWidth={2.5} />
        </span>
        <div
          className={cn(
            "flex-col leading-none",
            collapsed ? "hidden" : "hidden md:flex",
          )}
        >
          <span className="font-heading text-[15px] font-bold tracking-tight">
            Appli<span className="text-primary">nation</span>
          </span>
          <span className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            job pipeline
          </span>
        </div>
      </div>
      <ScrollArea className="flex-1 px-3 py-4">
        <nav className="flex flex-col gap-6">
          {navSections.map((section) => (
            <div key={section.label} className="flex flex-col gap-1">
              <span
                className={cn(
                  "px-3 pb-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground/70",
                  collapsed ? "hidden" : "hidden md:block",
                )}
              >
                {section.label}
              </span>
              {section.items.map((item) => {
                const active =
                  item.href === "/"
                    ? pathname === "/"
                    : pathname?.startsWith(item.href);
                const Icon = item.icon;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    title={item.label}
                    className={cn(
                      "group relative flex items-center justify-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-all duration-150",
                      !collapsed && "md:justify-start",
                      active
                        ? "bg-sidebar-accent text-sidebar-accent-foreground shadow-sm"
                        : "text-muted-foreground hover:bg-sidebar-accent/50 hover:text-sidebar-accent-foreground",
                    )}
                  >
                    {active && (
                      <span className="brand-gradient absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full" />
                    )}
                    <Icon
                      className={cn(
                        "size-4 shrink-0 transition-colors",
                        active
                          ? "text-primary"
                          : "text-muted-foreground group-hover:text-foreground",
                      )}
                    />
                    <span className={labelCls}>{item.label}</span>
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
      </ScrollArea>
      <div className="hidden shrink-0 flex-col gap-2 border-t border-sidebar-border p-3 md:flex">
        {!collapsed && (
          <div className="rounded-lg border border-sidebar-border bg-background/40 px-3 py-2">
            <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">
              Latest run
            </div>
            <div className="mt-1.5">
              <RunStatusPill />
            </div>
          </div>
        )}
        <Button
          variant="ghost"
          size="sm"
          onClick={toggleSidebar}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className={cn(
            "h-9 w-full gap-2 text-muted-foreground hover:text-foreground",
            collapsed ? "justify-center px-0" : "justify-start",
          )}
        >
          {collapsed ? (
            <PanelLeftOpen className="size-4 shrink-0" />
          ) : (
            <PanelLeftClose className="size-4 shrink-0" />
          )}
          <span className={labelCls}>Collapse</span>
        </Button>
      </div>
    </aside>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { setCommandOpen, setSidebarCollapsed, sidebarCollapsed, toggleSidebar } =
    useUI();
  const pathname = usePathname();

  // The onboarding wizard renders full-screen (no sidebar/header chrome).
  if (pathname.startsWith("/onboarding")) {
    return (
      <>
        <OnboardingGate />
        {children}
      </>
    );
  }

  // Restore the persisted collapse preference after mount (SSR renders the
  // expanded default, so this avoids a hydration mismatch).
  useEffect(() => {
    setSidebarCollapsed(readStoredSidebarCollapsed());
  }, [setSidebarCollapsed]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCommandOpen(true);
      } else if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "b") {
        e.preventDefault();
        toggleSidebar();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [setCommandOpen, toggleSidebar]);

  return (
    <div className="flex h-svh overflow-hidden">
      <Sidebar />
      <div className="flex h-svh min-w-0 flex-1 flex-col overflow-hidden">
        <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center justify-between border-b border-border bg-background/70 px-4 backdrop-blur-xl sm:px-6">
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              className="-ml-1 hidden size-8 text-muted-foreground hover:text-foreground md:inline-flex"
              onClick={toggleSidebar}
              title={sidebarCollapsed ? "Expand sidebar (⌘B)" : "Collapse sidebar (⌘B)"}
              aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            >
              {sidebarCollapsed ? (
                <PanelLeftOpen className="size-4" />
              ) : (
                <PanelLeftClose className="size-4" />
              )}
            </Button>
            <PageTitle />
          </div>
          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              size="sm"
              className="gap-2 text-muted-foreground"
              onClick={() => setCommandOpen(true)}
            >
              <Command className="size-3.5" />
              <span className="hidden sm:inline">Search</span>
              <kbd className="hidden rounded bg-muted px-1.5 py-0.5 text-[10px] sm:inline">
                ⌘K
              </kbd>
            </Button>
            <ThemeToggle />
          </div>
        </header>
        <main className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8">
          {children}
        </main>
      </div>
      <CommandPalette />
      <RunActivityWatcher />
      <OnboardingGate />
    </div>
  );
}
