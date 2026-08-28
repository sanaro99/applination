// Flatten the four editable config sections into labeled, comparable lines so
// `diffLines` can report what a save will change. Third sibling of
// `flattenMaster` and `flattenStory`.
//
// Labels are the ones the form shows, except for source keys: those stay the
// literal `sources.<key>` name, because that is what identifies a scraper in
// the file the user can also open on the Advanced tab.

import type { ConfigSections } from "./api";

const onOff = (v: boolean) => (v ? "on" : "off");

function list(lines: string[], label: string, items: string[]): void {
  lines.push(`§ ${label}`);
  for (const item of items) lines.push(`• ${item}`);
}

export function flattenConfig(cfg: ConfigSections): string[] {
  const lines: string[] = [];

  const s = cfg.search;
  lines.push("§ What to search for");
  lines.push(`Minimum match score: ${s.min_match_score}`);
  lines.push(`Jobs per run: ${s.max_jobs_per_day}`);
  lines.push(`Remote: ${onOff(s.remote_ok)}`);
  list(lines, "Keywords", s.keywords);
  list(lines, "Onsite cities", s.onsite_cities);
  list(lines, "Countries", s.countries);

  lines.push("§ Job boards");
  for (const t of cfg.sources.toggles) lines.push(`• ${t.key}: ${onOff(t.enabled)}`);
  list(lines, "Greenhouse companies", cfg.sources.greenhouse_extra_companies);

  const o = cfg.output;
  lines.push("§ Documents");
  lines.push(`Convert to PDF: ${onOff(o.produce_pdf)}`);
  lines.push(`Font: ${o.font_name}`);
  lines.push(`Font size: ${o.base_font_size}`);
  lines.push(`Margins: ${o.margins_inches}`);

  const r = cfg.reminders;
  lines.push("§ Reminders");
  lines.push(`Daily digest: ${onOff(r.digest_enabled)}`);
  lines.push(`Digest goes to: ${r.digest_to || "your account email"}`);
  lines.push(`Deadline window: ${r.deadline_window_days} days`);
  lines.push(`Follow up after: ${r.follow_up_days} days`);

  return lines;
}
