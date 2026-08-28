import { describe, expect, it } from "vitest";

import { diffLines } from "./resume-diff";
import { flattenConfig } from "./config-flatten";
import type { ConfigSections } from "./api";

const BASE: ConfigSections = {
  search: {
    keywords: ["software engineer intern"],
    min_match_score: 55,
    max_jobs_per_day: 20,
    remote_ok: true,
    onsite_cities: ["Remote"],
    countries: ["us"],
  },
  sources: {
    toggles: [
      { key: "remotive", enabled: true },
      { key: "adzuna", enabled: false },
    ],
    greenhouse_extra_companies: [],
  },
  output: {
    produce_pdf: true,
    font_name: "Times New Roman",
    base_font_size: 10,
    margins_inches: 0.25,
  },
  reminders: {
    digest_enabled: false,
    digest_to: "",
    deadline_window_days: 7,
    follow_up_days: 10,
  },
};

const clone = (c: ConfigSections): ConfigSections =>
  JSON.parse(JSON.stringify(c)) as ConfigSections;

const changes = (a: ConfigSections, b: ConfigSections) =>
  diffLines(flattenConfig(a), flattenConfig(b)).filter((l) => l.type !== "same");

describe("flattenConfig", () => {
  it("reports a changed number as one replaced line", () => {
    const after = clone(BASE);
    after.search.min_match_score = 70;
    expect(changes(BASE, after)).toEqual([
      { type: "remove", text: "Minimum match score: 55" },
      { type: "add", text: "Minimum match score: 70" },
    ]);
  });

  it("names a source by its config key so the line is unambiguous", () => {
    const after = clone(BASE);
    after.sources.toggles[1].enabled = true;
    expect(changes(BASE, after)).toEqual([
      { type: "remove", text: "• adzuna: off" },
      { type: "add", text: "• adzuna: on" },
    ]);
  });

  it("reports one added keyword as one addition, not a rewritten list", () => {
    const after = clone(BASE);
    after.search.keywords.push("sre intern");
    expect(changes(BASE, after)).toEqual([
      { type: "add", text: "• sre intern" },
    ]);
  });

  it("reports nothing for a no-op", () => {
    expect(changes(BASE, clone(BASE))).toEqual([]);
  });

  it("renders a boolean as on/off rather than true/false", () => {
    expect(flattenConfig(BASE)).toContain("Convert to PDF: on");
  });
});
