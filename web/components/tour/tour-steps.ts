/** What the tour knows about the account, so steps can drop themselves. */
export interface TourContext {
  hasApplications: boolean;
}

/** Which side of the spotlighted element the card prefers to sit on. */
export type TourSide = "top" | "bottom" | "left" | "right";

interface TourStepDef {
  path: string;
  /** CSS selector for the element to spotlight. Omit to center the card. */
  selector?: string;
  title: string;
  content: string;
  /** Ignored when `selector` is omitted (the card centers regardless). */
  side?: TourSide;
  /** Extra clearance (px) kept below a fixed header when scrolled into view. */
  scrollOffset?: number;
  /** Omitted from the tour when this returns false. Default: always shown. */
  when?: (ctx: TourContext) => boolean;
}

export interface TourStep extends Omit<TourStepDef, "when"> {
  /** Set by `buildTour` for the first step on a page the tour navigated to. */
  navHint?: string;
}

/** Clears the 56px sticky header plus room for the demo banner above it. */
const HEADER_CLEARANCE = 96;

const STEPS: TourStepDef[] = [
  {
    path: "/",
    // No selector: the engine centers the card, which is what a welcome wants.
    title: "Welcome to Applination",
    content:
      "This is an AI-assisted job application pipeline: it finds postings, scores them against your background, and writes a tailored resume and cover letter for the best matches. Here is the two-minute version.",
  },
  {
    path: "/",
    selector: "#tour-dashboard-stats",
    title: "Your pipeline at a glance",
    content:
      "Applications tracked, pipeline runs completed, the average fit score across them, and how many you have actually applied to.",
    side: "bottom",
    scrollOffset: HEADER_CLEARANCE,
  },
  {
    path: "/",
    selector: "#tour-reminders",
    title: "Never miss a deadline",
    content:
      "Subscribe your calendar app to a live feed of deadlines and interviews, and have a daily digest emailed to you. Both stay in sync as your applications change.",
    side: "top",
    scrollOffset: HEADER_CLEARANCE,
  },
  {
    path: "/",
    selector: "#tour-sidebar-nav",
    title: "Four places to work",
    content:
      "Workspace is the pipeline itself. Prepwork is the interview and essay help. Insights is run history and stats. Setup is where your keys, LLM routing and master data live.",
    side: "right",
  },
  {
    path: "/run",
    selector: "#tour-run-config",
    title: "One run does the whole loop",
    content:
      "A run fetches postings from eight public job boards, ranks every one of them against your resume, then tailors documents for the top matches and writes a dated Excel tracker.",
    side: "bottom",
    scrollOffset: HEADER_CLEARANCE,
  },
  {
    path: "/run",
    selector: "#tour-run-start",
    title: "Watch it happen live",
    content:
      "Starting a run streams every stage back to this page as it happens — fetching, ranking, then each document as it is generated. You can leave the page; it keeps going.",
    side: "top",
    scrollOffset: HEADER_CLEARANCE,
  },
  {
    path: "/applications",
    selector: "#tour-applications-tabs",
    title: "Everything you have applied to",
    content:
      "A sortable table, or a drag-and-drop kanban by status. Open any row for the generated resume and cover letter, a diff between resume versions, and inline editing.",
    side: "bottom",
    scrollOffset: HEADER_CLEARANCE,
  },
  {
    path: "/applications",
    selector: "#tour-first-application",
    title: "Open one to see the work",
    content:
      "Each row holds the resume and cover letter written for that specific posting — rewritten bullet by bullet against the job description, not a template with the company name swapped in.",
    side: "bottom",
    scrollOffset: HEADER_CLEARANCE,
    // A fresh account has an empty table and no row to point at.
    when: (ctx) => ctx.hasApplications,
  },
  {
    path: "/applications",
    selector: "#tour-inbox-sync",
    title: "Close the loop from your inbox",
    content:
      "Connect Gmail and this reads replies from companies you applied to, then moves each application forward on its own — interview scheduled, rejected, offer. Classification runs inside your browser, so the emails never leave it.",
    side: "bottom",
    scrollOffset: HEADER_CLEARANCE,
  },
  {
    path: "/coach",
    selector: "#tour-coach-composer",
    title: "Prep with something that knows you",
    content:
      "Coach, mock interviews and the essay drafter all read your resume, bio and stories, so the answers are grounded in your actual experience. Good replies can be saved to an answer bank and reused.",
    side: "top",
    scrollOffset: HEADER_CLEARANCE,
  },
  {
    path: "/config",
    selector: "#tour-providers",
    title: "Your keys, your models",
    content:
      "Bring your own API key for any supported provider — it is encrypted at rest and never shared. The Workflows page then routes each task (ranking, tailoring, cover letters) to whichever model you prefer.",
    side: "bottom",
    scrollOffset: HEADER_CLEARANCE,
  },
  {
    path: "/",
    selector: "#tour-user-menu",
    title: "That's the tour",
    content:
      "Have a look around — nothing here is locked. If you want this walkthrough again, it lives in this menu and in the ⌘K palette.",
    side: "bottom",
  },
];

/** Sidebar nav group + label for each path, shown as a breadcrumb. */
const PATH_LABELS: Record<string, string> = {
  "/": "Workspace · Dashboard",
  "/run": "Workspace · Run",
  "/applications": "Workspace · Applications",
  "/coach": "Prepwork · Coach",
  "/config": "Setup · Config",
};

/** Where a replay must navigate to before starting the tour. */
export const TOUR_START_PATH = STEPS[0].path;

/** Filters steps this account can actually show, then adds nav breadcrumbs. */
export function buildTour(ctx: TourContext): TourStep[] {
  const kept = STEPS.filter((s) => s.when?.(ctx) ?? true);

  return kept.map((def, i): TourStep => {
    const prevPath = kept[i - 1]?.path;
    const changedPage = i > 0 && def.path !== prevPath;
    const step: Partial<TourStepDef> = { ...def };
    delete step.when;
    return {
      ...step,
      ...(changedPage ? { navHint: PATH_LABELS[def.path] } : {}),
    } as TourStep;
  });
}
