/**
 * Fingerprint ridge geometry.
 *
 * Pure and separate from the component so it can be reasoned about (and, once
 * this repo has a JS test runner, tested) without a DOM. Ridges are concentric
 * arcs, innermost first, matching the ridge order the API returns — ridge N
 * always means the same thing, so the shape a user watches fill is stable
 * across sessions.
 *
 * The order below must stay in step with `RIDGES` in server/profile_strength.py;
 * a ridge id the API sends that is missing here simply never renders.
 */
export const RIDGE_ORDER = [
  "contact",
  "material",
  "resume",
  "story_1",
  "story_2",
  "story_3",
  "voice",
  "search",
  "provider",
] as const;

const CENTER = 60;
const INNER_RADIUS = 8;
const RIDGE_GAP = 5.5;

/** An open arc, flattened slightly so it reads as a fingerprint, not a target. */
export function ridgePath(index: number): string {
  const r = INNER_RADIUS + index * RIDGE_GAP;
  const ry = r * 1.18;
  // Leave a gap at the bottom so the rings read as ridges rather than circles.
  const startAngle = 115;
  const endAngle = 425;
  const rad = (deg: number) => (deg * Math.PI) / 180;
  const x1 = CENTER + r * Math.cos(rad(startAngle));
  const y1 = CENTER + ry * Math.sin(rad(startAngle));
  const x2 = CENTER + r * Math.cos(rad(endAngle));
  const y2 = CENTER + ry * Math.sin(rad(endAngle));
  return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r.toFixed(2)} ${ry.toFixed(2)} 0 1 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
}

/** How much of a ridge is drawn. A draft story is genuinely half-done. */
export function fillFraction(state: string): number {
  if (state === "filled") return 1;
  if (state === "partial") return 0.5;
  return 0;
}
