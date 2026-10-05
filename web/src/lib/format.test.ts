import { age, minutesToCutoff, money } from "./format";
import { needsCheck } from "./lines";
import type { Line } from "./types";

test("money is formatted from integer fils", () => {
  expect(money(123456)).toBe("1,234.56");
  expect(money(5)).toBe("0.05");
});

test("cut-off is counted in Dubai time whatever the browser's zone", () => {
  expect(minutesToCutoff(new Date("2026-10-05T08:00:00Z"))).toBe(4 * 60); // 12:00 in Dubai
  expect(minutesToCutoff(new Date("2026-10-05T13:30:00Z"))).toBe(-90); // 17:30 in Dubai
});

test("ages read naturally", () => {
  expect(age(0)).toBe("just now");
  expect(age(75)).toBe("1 h 15 min");
});

const base: Line = {
  position: 0, sku: "SL-1", product: null, qty: 1, unit: "carton", qty_base: 24, unit_price_fils: 100, amount_fils: 2400,
  source_text: "x", unit_from: "customer", confidence: 0.97, flags: [], edited: false, substitutes: [], why: null, candidates: [],
};

test("a line needs a look when unmatched, unsure, out of stock or the unit was guessed, unless a person edited it", () => {
  expect(needsCheck(base)).toBe(false);
  expect(needsCheck({ ...base, sku: null })).toBe(true);
  expect(needsCheck({ ...base, confidence: 0.6 })).toBe(true);
  expect(needsCheck({ ...base, confidence: 0.6, edited: true })).toBe(false);
  expect(needsCheck({ ...base, flags: ["out_of_stock"] })).toBe(true);
  expect(needsCheck({ ...base, flags: ["unit_from_history"] })).toBe(false);
});
