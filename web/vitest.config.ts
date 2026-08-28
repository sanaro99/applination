import { defineConfig } from "vitest/config";

// Scoped to pure functions in lib/ on purpose. Components and visuals are
// verified by build + lint and by the user looking at them; what needs a test
// here is logic whose failure mode is showing someone a false account of their
// own changes.
export default defineConfig({
  test: {
    include: ["lib/**/*.test.ts"],
    environment: "node",
  },
});
