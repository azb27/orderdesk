import type { Line } from "./types";

/** Lines at or above this probability of being right are shown as settled; the rest are tinted for a look. */
export const SURE = 0.9;

export function needsCheck(l: Line): boolean {
  return l.sku === null || (!l.edited && l.confidence < SURE) || l.flags.some((f) => ["out_of_stock", "unit_guessed", "bad_quantity", "unresolved"].includes(f));
}
