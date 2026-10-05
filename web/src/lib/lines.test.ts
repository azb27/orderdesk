import { describe, expect, it } from "vitest";
import type { Line, Product } from "./types";
import { needsCheck, shouldOfferToTeach } from "./lines";

const product = (id: string, family: string): Product => ({ id, family, name_en: id, name_ar: "", size_label: "", pack_size: 0, carton_size: 12, stock_on_hand: 10 });
const water15 = product("SL-1", "al_wadi");
const line = (over: Partial<Line> = {}): Line => ({
  position: 0, sku: water15.id, product: water15, qty: 2, unit: "carton", qty_base: 24, unit_price_fils: 100, amount_fils: 2400,
  source_text: "abi 2 kartoon mai 1.5", unit_from: "customer", confidence: 0.95, flags: [], edited: false, substitutes: [], why: null, candidates: [],
  ...over,
});

describe("shouldOfferToTeach", () => {
  it("offers when the person picked a different product", () => {
    expect(shouldOfferToTeach(line(), product("SL-9", "crystal_oasis"))).toBe(true);
  });
  it("stays quiet for another size of the same product", () => {
    expect(shouldOfferToTeach(line(), product("SL-2", "al_wadi"))).toBe(false);
  });
  it("stays quiet for an out-of-stock substitute", () => {
    const sub = product("SL-9", "crystal_oasis");
    expect(shouldOfferToTeach(line({ flags: ["out_of_stock"], substitutes: [sub] }), sub)).toBe(false);
  });
  it("stays quiet for lines from the last order", () => {
    expect(shouldOfferToTeach(line({ flags: ["from_last_order"] }), product("SL-9", "crystal_oasis"))).toBe(false);
  });
});

describe("needsCheck", () => {
  it("flags an unusual quantity until a person edits the line", () => {
    expect(needsCheck(line({ flags: ["unusual_qty"] }))).toBe(true);
    expect(needsCheck(line({ flags: ["unusual_qty"], edited: true }))).toBe(false);
  });
});
