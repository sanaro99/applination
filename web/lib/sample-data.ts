/**
 * Sample answers, for anyone who would rather look around than type.
 *
 * The persona is John Doe, the same fictional person as demo_data/. Kept as
 * frontend constants rather than served from the demo fixture: the fixture is a
 * full config + master_data tree, and reshaping it into chapter-sized snippets
 * would be more coupling than the reuse is worth.
 *
 * Anything filled from here MUST stay visibly marked — see sample-data-banner.
 */
export const SAMPLE = {
  notes:
    "I've been doing backend work for about four years, mostly Python and " +
    "Postgres. Last couple of years at a payments company where I looked " +
    "after the ledger service. Before that a smaller startup doing " +
    "everything from React to deploys.",
  story: {
    title: "The ledger migration",
    body:
      "We moved the ledger off a single Postgres box onto a partitioned " +
      "setup. The actual migration was fine — the annoying part was that " +
      "nobody could agree on what a 'transaction' meant across three teams, " +
      "so I spent more time in a room with a whiteboard than in the code. " +
      "Shipped it over a weekend with no downtime.",
  },
  keywords: ["Backend Engineer", "Python", "distributed systems", "Postgres"],
  contact: {
    full_name: "John Doe",
    email: "john.doe@example.com",
    phone: "+1 555 0100",
    location_city: "Seattle, WA",
  },
} as const;
