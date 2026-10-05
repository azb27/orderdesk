import type { Line, Product } from "./types";

/** Lines at or above this probability of being right are shown as settled; the rest are tinted for a look. */
export const SURE = 0.9;

export function needsCheck(l: Line): boolean {
  if (l.sku === null || l.flags.some((f) => ["out_of_stock", "unit_guessed", "bad_quantity", "unresolved"].includes(f))) return true;
  // once a person has edited the line, low confidence and an unusual quantity are theirs to judge
  return !l.edited && (l.confidence < SURE || l.flags.includes("unusual_qty"));
}

/** Offer to remember a name only when the person corrected *which product* the words mean. A substitute for an
 *  out-of-stock line or another size of the same product says nothing about the words. */
export function shouldOfferToTeach(l: Line, p: Product): boolean {
  if (!l.source_text || l.source_text.startsWith("(") || l.flags.includes("from_last_order")) return false;
  if (l.substitutes.some((s) => s.id === p.id)) return false;
  return l.product === null || l.product.family !== p.family;
}
