import type { Step } from "nextstepjs";

/** The single tour's name. `startNextStep(TOUR_NAME)` replays it. */
export const TOUR_NAME = "product-tour";

/**
 * What the tour knows about the account it is running against. Steps use this
 * to drop themselves rather than point at an element that was never rendered.
 */
export interface TourContext {
  hasApplications: boolean;
}

/**
 * A step plus the page it lives on. `path` replaces nextstepjs's per-step
 * `nextRoute`/`prevRoute`, which are derived in `buildTour` once the list has
 * been filtered — hardcoding them breaks the moment a step drops out.
 */
interface TourStepDef extends Omit<Step, "nextRoute" | "prevRoute"> {
  path: string;
  /** Omitted from the tour when this returns false. Default: always shown. */
  when?: (ctx: TourContext) => boolean;
}

/**
 * Clearance kept above a highlighted element when it is scrolled into view:
 * the 56px sticky header, plus room for the demo banner above it.
 */
const HEADER_CLEARANCE = 96;

/**
 * Content mounts behind data fetches (TanStack Query) and route transitions, so
 * every anchored step retries its selector for ~2s before giving up.
 */
const RETRY: Pick<Step, "selectorRetryAttempts" | "selectorRetryDelay"> = {
  selectorRetryAttempts: 10,
  selectorRetryDelay: 200,
};

const STEPS: TourStepDef[] = [
  {
    path: "/",
    // No selector: nextstepjs centers the card, which is what a welcome wants.
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
    ...RETRY,
  },
  {
    path: "/",
    selector: "#tour-reminders",
    title: "Never miss a deadline",
    content:
      "Subscribe your calendar app to a live feed of deadlines and interviews, and have a daily digest emailed to you. Both stay in sync as your applications change.",
    side: "top",
    scrollOffset: HEADER_CLEARANCE,
    ...RETRY,
  },
  {
    path: "/",
    selector: "#tour-sidebar-nav",
    title: "Four places to work",
    content:
      "Workspace is the pipeline itself. Prepwork is the interview and essay help. Insights is run history and stats. Setup is where your keys, LLM routing and master data live.",
    side: "right",
    ...RETRY,
  },
  {
    path: "/run",
    selector: "#tour-run-config",
    title: "One run does the whole loop",
    content:
      "A run fetches postings from eight public job boards, ranks every one of them against your resume, then tailors documents for the top matches and writes a dated Excel tracker.",
    side: "bottom",
    scrollOffset: HEADER_CLEARANCE,
    ...RETRY,
  },
  {
    path: "/run",
    selector: "#tour-run-start",
    title: "Watch it happen live",
    content:
      "Starting a run streams every stage back to this page as it happens — fetching, ranking, then each document as it is generated. You can leave the page; it keeps going.",
    side: "top",
    scrollOffset: HEADER_CLEARANCE,
    ...RETRY,
  },
  {
    path: "/applications",
    selector: "#tour-applications-tabs",
    title: "Everything you have applied to",
    content:
      "A sortable table, or a drag-and-drop kanban by status. Open any row for the generated resume and cover letter, a diff between resume versions, and inline editing.",
    side: "bottom",
    scrollOffset: HEADER_CLEARANCE,
    ...RETRY,
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
    ...RETRY,
  },
  {
    path: "/applications",
    selector: "#tour-inbox-sync",
    title: "Close the loop from your inbox",
    content:
      "Connect Gmail and this reads replies from companies you applied to, then moves each application forward on its own — interview scheduled, rejected, offer. Classification runs inside your browser, so the emails never leave it.",
    // The anchor sits flush against the right edge of its header; "-left"
    // grows the card rightward off-screen. "-right" grows it leftward, into
    // the page, which is the only direction with room.
    side: "bottom-right",
    scrollOffset: HEADER_CLEARANCE,
    ...RETRY,
  },
  {
    path: "/coach",
    selector: "#tour-coach-composer",
    title: "Prep with something that knows you",
    content:
      "Coach, mock interviews and the essay drafter all read your resume, bio and stories, so the answers are grounded in your actual experience. Good replies can be saved to an answer bank and reused.",
    side: "top",
    scrollOffset: HEADER_CLEARANCE,
    ...RETRY,
  },
  {
    path: "/config",
    selector: "#tour-providers",
    title: "Your keys, your models",
    content:
      "Bring your own API key for any supported provider — it is encrypted at rest and never shared. The Workflows page then routes each task (ranking, tailoring, cover letters) to whichever model you prefer.",
    side: "bottom",
    scrollOffset: HEADER_CLEARANCE,
    ...RETRY,
  },
  {
    path: "/",
    selector: "#tour-user-menu",
    title: "That's the tour",
    content:
      "Have a look around — nothing here is locked. If you want this walkthrough again, it lives in this menu and in the ⌘K palette.",
    // Same fix as the inbox-sync step above: this anchor is also flush
    // against the right edge of the header.
    side: "bottom-right",
    ...RETRY,
  },
];

/**
 * `Step` plus the nav breadcrumb `buildTour` derives for a page-changing step.
 * Not part of nextstepjs's own `Step` — read via this type in `TourCard`.
 */
export interface TourStep extends Step {
  navHint?: string;
}

/**
 * Sidebar nav group + label for each path a step can land on, shown as a
 * breadcrumb so a step that jumps to a new page tells you which nav tab it
 * came from — the tour otherwise teleports the user with no explanation of
 * how they'd get there themselves.
 */
const PATH_LABELS: Record<string, string> = {
  "/": "Workspace · Dashboard",
  "/run": "Workspace · Run",
  "/applications": "Workspace · Applications",
  "/coach": "Prepwork · Coach",
  "/config": "Setup · Config",
};

/**
 * Where the tour has to be standing before it starts. The opening step is
 * unconditional, so this holds whatever the filtering does — but a replay
 * launched from another page still has to navigate here first, or step two
 * would hunt for a dashboard element on someone else's page.
 */
export const TOUR_START_PATH = STEPS[0].path;

/**
 * Drops the tour's own bookkeeping fields, leaving a plain nextstepjs `Step`.
 * `path` and `when` describe how the tour is assembled; passing them through
 * to the library would be meaningless.
 */
function toStep(def: TourStepDef): Step {
  const step: Partial<TourStepDef> = { ...def };
  delete step.path;
  delete step.when;
  return step as Step;
}

/**
 * Filters the steps down to what this account can actually show, then derives
 * `nextRoute`/`prevRoute` from where consecutive steps live. Deriving is the
 * point: a dropped step would otherwise leave its neighbour navigating to a
 * page the tour no longer visits.
 */
export function buildTour(ctx: TourContext): TourStep[] {
  const kept = STEPS.filter((s) => s.when?.(ctx) ?? true);

  return kept.map((def, i): TourStep => {
    const nextPath = kept[i + 1]?.path;
    const prevPath = kept[i - 1]?.path;
    // Only the first step of a fresh page gets the breadcrumb — the opening
    // welcome step (i === 0) has nothing to compare against, and later steps
    // on the same page already got it once.
    const changedPage = i > 0 && def.path !== prevPath;
    return {
      ...toStep(def),
      ...(nextPath && nextPath !== def.path ? { nextRoute: nextPath } : {}),
      ...(prevPath && prevPath !== def.path ? { prevRoute: prevPath } : {}),
      ...(changedPage ? { navHint: PATH_LABELS[def.path] } : {}),
    };
  });
}
