// Flatten a tailored resume JSON into labeled, comparable lines and compute a
// line-level diff between two versions. Used by the tweak panel to show what an
// instruction actually changed (summary text, experience/project bullets, skills).

export interface DiffLine {
  type: "same" | "add" | "remove";
  text: string;
}

type ResumeJson = Record<string, unknown>;

function asText(v: unknown): string {
  return (v ?? "").toString().trim();
}

export function flattenResume(r: ResumeJson): string[] {
  const lines: string[] = [];

  const summary = asText(r.summary);
  if (summary) lines.push("§ Summary", summary);

  const experience = Array.isArray(r.experience) ? r.experience : [];
  for (const e of experience as Record<string, unknown>[]) {
    const role = asText(e?.role);
    const company = asText(e?.company);
    lines.push(`§ Experience — ${[role, company].filter(Boolean).join(" @ ")}`);
    const bullets = Array.isArray(e?.bullets) ? e.bullets : [];
    for (const b of bullets) lines.push(`• ${asText(b)}`);
  }

  const projects = Array.isArray(r.projects) ? r.projects : [];
  for (const p of projects as Record<string, unknown>[]) {
    lines.push(`§ Project — ${asText(p?.name)}`);
    const bullets = Array.isArray(p?.bullets) ? p.bullets : [];
    for (const b of bullets) lines.push(`• ${asText(b)}`);
  }

  const skills = r.skills;
  if (Array.isArray(skills) && skills.length) {
    lines.push("§ Skills");
    for (const s of skills) {
      if (typeof s === "string") {
        lines.push(`• ${s.trim()}`);
      } else if (s && typeof s === "object") {
        const o = s as Record<string, unknown>;
        const cat = asText(o.category ?? o.name);
        const items = Array.isArray(o.items)
          ? o.items.join(", ")
          : asText(o.items);
        lines.push(`• ${[cat, items].filter(Boolean).join(": ")}`);
      }
    }
  }

  return lines.filter((l) => l.length > 0);
}

export function diffLines(oldLines: string[], newLines: string[]): DiffLine[] {
  const n = oldLines.length;
  const m = newLines.length;
  // LCS length table.
  const dp: number[][] = Array.from({ length: n + 1 }, () =>
    new Array<number>(m + 1).fill(0),
  );
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] =
        oldLines[i] === newLines[j]
          ? dp[i + 1][j + 1] + 1
          : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (oldLines[i] === newLines[j]) {
      out.push({ type: "same", text: oldLines[i] });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      out.push({ type: "remove", text: oldLines[i] });
      i++;
    } else {
      out.push({ type: "add", text: newLines[j] });
      j++;
    }
  }
  while (i < n) out.push({ type: "remove", text: oldLines[i++] });
  while (j < m) out.push({ type: "add", text: newLines[j++] });
  return out;
}
