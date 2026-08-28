import { describe, expect, it } from "vitest";

import { diffLines } from "./resume-diff";
import { flattenMaster } from "./master-flatten";

const BASE = {
  summary_options: ["Engineer who ships"],
  core_skills: ["Python", "SQL"],
  skills: { languages: ["Python"] },
  experience: [
    {
      company: "Example Corp",
      role: "Software Engineer",
      bullets_all: ["Built the thing", "Owned the release"],
    },
  ],
  education: [{ school: "State University", degree: "BS CS" }],
};

const changes = (a: object, b: object) =>
  diffLines(flattenMaster(a), flattenMaster(b)).filter((l) => l.type !== "same");

describe("flattenMaster", () => {
  it("labels a job with its role and company", () => {
    expect(flattenMaster(BASE)).toContain(
      "§ Jobs — Software Engineer @ Example Corp",
    );
  });

  it("renders each bullet as its own line", () => {
    expect(flattenMaster(BASE)).toContain("• Built the thing");
    expect(flattenMaster(BASE)).toContain("• Owned the release");
  });

  it("survives an empty document", () => {
    expect(flattenMaster({})).toEqual([]);
  });
});

describe("diffing a flattened master resume", () => {
  it("reports no changes for an identical document", () => {
    expect(changes(BASE, BASE)).toEqual([]);
  });

  it("reports a bullet removed from the middle as one removal", () => {
    const after = {
      ...BASE,
      experience: [{ ...BASE.experience[0], bullets_all: ["Owned the release"] }],
    };
    const diff = changes(BASE, after);
    expect(diff).toHaveLength(1);
    expect(diff[0]).toEqual({ type: "remove", text: "• Built the thing" });
  });

  it("reports an edited bullet as one removal and one addition", () => {
    const after = {
      ...BASE,
      experience: [
        {
          ...BASE.experience[0],
          bullets_all: ["Built the thing faster", "Owned the release"],
        },
      ],
    };
    const diff = changes(BASE, after);
    expect(diff.filter((l) => l.type === "remove")).toHaveLength(1);
    expect(diff.filter((l) => l.type === "add")).toHaveLength(1);
  });

  it("reports an emptied section as removals, not a crash", () => {
    const diff = changes(BASE, { ...BASE, core_skills: [] });
    expect(diff.every((l) => l.type === "remove")).toBe(true);
    expect(diff.length).toBeGreaterThan(0);
  });

  it("reports a reordered pair of bullets as exactly one move's worth of noise", () => {
    // A line diff cannot express a move: it shows one side removed and re-added.
    // Pinned so improving it later is a deliberate change, not a surprise.
    const after = {
      ...BASE,
      experience: [
        {
          ...BASE.experience[0],
          bullets_all: ["Owned the release", "Built the thing"],
        },
      ],
    };
    const diff = changes(BASE, after);
    expect(diff).toHaveLength(2);
    expect(diff.map((l) => l.type).sort()).toEqual(["add", "remove"]);
  });
});
