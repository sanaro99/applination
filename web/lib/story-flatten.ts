// Flatten one story into labeled, comparable lines so `diffLines` can report
// what a save will change. Sibling of `flattenMaster`; the shape is different
// enough (a prose body, three parallel tag lists) that sharing the code would
// cost more than it saves.
//
// Tags get one line each rather than one comma-joined line, because adding a
// single tag should read as one addition, not as a rewritten line.

import type { StoryDoc } from "./api";

const LISTS: [keyof StoryDoc, string][] = [
  ["tags", "Tags"],
  ["role_fit", "Fits these roles"],
  ["company_fit", "Fits these companies"],
];

export function flattenStory(doc: StoryDoc): string[] {
  const lines: string[] = [];

  const title = (doc.title ?? "").trim();
  if (title) lines.push("§ Title", title);

  for (const [key, label] of LISTS) {
    const items = (Array.isArray(doc[key]) ? (doc[key] as string[]) : [])
      .map((t) => t.trim())
      .filter(Boolean);
    if (items.length) {
      lines.push(`§ ${label}`);
      for (const item of items) lines.push(`• ${item}`);
    }
  }

  const hook = (doc.one_liner ?? "").trim();
  if (hook) lines.push("§ Hook", hook);

  const body = (doc.body ?? "").trim();
  if (body) lines.push("§ Story", ...body.split("\n"));

  return lines;
}
