import type { Line } from "./types";

/** Lines at or above this probability of being right are shown as settled; the rest are tinted for a look. */
export const SURE = 0.9;

export function needsCheck(l: Line): boolean {
  if (l.sku === null || l.flags.some((f) => ["out_of_stock", "unit_guessed", "bad_quantity", "unresolved"].includes(f))) return true;
  // once a person has edited the line, low confidence and an unusual quantity are theirs to judge
  return !l.edited && (l.confidence < SURE || l.flags.includes("unusual_qty"));
}
