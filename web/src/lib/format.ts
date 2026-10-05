// Formatting at the edge: money is integer fils everywhere else.
const aed = new Intl.NumberFormat("en-AE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const time = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Dubai" });
const day = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "Asia/Dubai" });

export const money = (fils: number): string => aed.format(fils / 100);
export const clock = (iso: string): string => time.format(new Date(iso));
export const shortDate = (iso: string): string => day.format(new Date(iso));

export function age(minutes: number): string {
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  return h < 24 ? `${h} h ${minutes % 60} min` : `${Math.floor(h / 24)} d`;
}

export const UNIT_LABEL: Record<string, string> = { carton: "ctn", pack: "pack", piece: "pc" };

export const FLAG_TEXT: Record<string, string> = {
  unresolved: "Couldn't match a product",
  bad_quantity: "Quantity unclear",
  unit_from_history: "Unit from their usual order",
  unit_guessed: "Unit guessed",
  out_of_stock: "Out of stock",
  low_stock: "Low stock",
  from_last_order: "From their last order",
};

export const HOLD_TEXT: Record<string, string> = {
  credit_hold: "Over credit limit",
  needs_review: "Needs a look",
  unknown_customer: "Unknown number",
};

/** Minutes left until the 16:00 Dubai cut-off (negative after it). */
export function minutesToCutoff(now = new Date()): number {
  const parts = new Intl.DateTimeFormat("en-GB", { hour: "numeric", minute: "numeric", hourCycle: "h23", timeZone: "Asia/Dubai" }).formatToParts(now);
  const h = Number(parts.find((p) => p.type === "hour")?.value ?? 0);
  const m = Number(parts.find((p) => p.type === "minute")?.value ?? 0);
  return 16 * 60 - (h * 60 + m);
}
