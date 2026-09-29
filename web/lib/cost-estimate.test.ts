import { describe, expect, it } from "vitest";
import { estimateRun, formatUsd } from "./cost-estimate";

describe("local ranking cost estimates", () => {
  it("charges no model cost for a local-ranking dry run", () => {
    expect(estimateRun(200, { dryRun: true, rankingMethod: "bm25" }).usd).toBe(0);
  });

  it("retains generation cost while removing only local ranking cost", () => {
    expect(estimateRun(10, { rankingMethod: "bm25" }).usd).toBeCloseTo(0.05);
    expect(estimateRun(10).usd).toBeCloseTo(0.08);
  });

  it("shows zero cost explicitly", () => {
    expect(formatUsd(0)).toBe("$0.00");
  });
});
