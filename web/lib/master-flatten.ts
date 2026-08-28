// Flatten a MASTER resume into labeled, comparable lines so `diffLines` can
// report what a save will change. The sibling `flattenResume` in resume-diff.ts
// does the same job for the TAILORED shape, which has different keys
// (`bullets` not `bullets_all`, one `summary` not `summary_options`) and is not
// reusable here.
//
// Section headings are the user-facing names, not the YAML keys, because these
// lines are shown to the person deciding whether to save.

type Master = Record<string, unknown>;

function asText(v: unknown): string {
  return (v ?? "").toString().trim();
}

function asList(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

function entryHeading(label: string, parts: string[]): string {
  const named = parts.filter(Boolean).join(" @ ");
  return named ? `§ ${label} — ${named}` : `§ ${label}`;
}

function bullets(entry: Record<string, unknown>, lines: string[]): void {
  for (const b of asList(entry.bullets_all)) {
    const text = asText(b);
    if (text) lines.push(`• ${text}`);
  }
}

export function flattenMaster(data: Master): string[] {
  const lines: string[] = [];

  const profile = (data.profile ?? {}) as Record<string, unknown>;
  const titles = asList(profile.identity_titles).map(asText).filter(Boolean);
  if (titles.length || profile.seniority) {
    lines.push("§ Who you are");
    if (titles.length) lines.push(`Titles: ${titles.join(", ")}`);
    if (profile.seniority) lines.push(`Level: ${asText(profile.seniority)}`);
  }

  const summaries = asList(data.summary_options).map(asText).filter(Boolean);
  if (summaries.length) {
    lines.push("§ How you describe yourself");
    for (const s of summaries) lines.push(`• ${s}`);
  }

  for (const [key, label] of [
    ["core_skills", "Skills you always list"],
    ["ats_adjacent_skills", "Skills to add when a job asks"],
  ] as const) {
    const items = asList(data[key]).map(asText).filter(Boolean);
    if (items.length) {
      lines.push(`§ ${label}`);
      for (const item of items) lines.push(`• ${item}`);
    }
  }

  // Canonical since PR #57: a mapping of group name to items.
  const skills = data.skills;
  if (skills && typeof skills === "object" && !Array.isArray(skills)) {
    const groups = Object.entries(skills as Record<string, unknown>);
    if (groups.length) {
      lines.push("§ Skill groups");
      for (const [group, items] of groups) {
        const listed = asList(items).map(asText).filter(Boolean).join(", ");
        lines.push(`• ${group}: ${listed}`);
      }
    }
  }

  for (const entry of asList(data.experience) as Record<string, unknown>[]) {
    lines.push(entryHeading("Jobs", [asText(entry.role), asText(entry.company)]));
    bullets(entry, lines);
  }

  for (const entry of asList(data.projects) as Record<string, unknown>[]) {
    lines.push(entryHeading("Projects", [asText(entry.name)]));
    bullets(entry, lines);
  }

  for (const entry of asList(data.education) as Record<string, unknown>[]) {
    lines.push(
      entryHeading("Education", [asText(entry.degree), asText(entry.school)]),
    );
  }

  return lines;
}
