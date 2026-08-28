import { describe, expect, it } from "vitest";

import { diffLines } from "./resume-diff";
import { flattenStory } from "./story-flatten";

const BASE = {
  title: "Monitoring dashboard",
  tags: ["platform", "devtools"],
  role_fit: ["swe"],
  company_fit: ["enterprise"],
  one_liner: "Cut detection time by 60% for 30+ teams.",
  body: "**Context**: no shared view.\n\n**What I did**: built one.",
};

const changes = (a: typeof BASE, b: typeof BASE) =>
  diffLines(flattenStory(a), flattenStory(b)).filter((l) => l.type !== "same");

describe("flattenStory", () => {
  it("labels each field with the name the editor shows", () => {
    const lines = flattenStory(BASE);
    expect(lines).toContain("§ Title");
    expect(lines).toContain("§ Tags");
    expect(lines).toContain("Monitoring dashboard");
  });

  it("renders each tag as its own line so one added tag is one change", () => {
    const after = { ...BASE, tags: ["platform", "devtools", "sre"] };
    expect(changes(BASE, after)).toEqual([{ type: "add", text: "• sre" }]);
  });

  it("keeps the body as separate lines so a one-paragraph edit is not a rewrite", () => {
    const after = { ...BASE, body: "**Context**: no shared view.\n\n**What I did**: built two." };
    expect(changes(BASE, after)).toHaveLength(2);
  });

  it("reports nothing for a no-op", () => {
    expect(changes(BASE, { ...BASE })).toEqual([]);
  });

  it("drops a field that has been emptied rather than showing a blank line", () => {
    const after = { ...BASE, one_liner: "" };
    expect(flattenStory(after)).not.toContain("§ Hook");
  });

  it("survives a document whose lists are missing entirely", () => {
    expect(() =>
      flattenStory({ title: "T" } as unknown as typeof BASE),
    ).not.toThrow();
  });
});
