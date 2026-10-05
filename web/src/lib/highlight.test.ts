import { highlightParts } from "./highlight";

test("marks the source words even with different spacing and case", () => {
  const parts = highlightParts("Hi boss\nAL WADI water  500 ml 3 ctn\nthanks", "al wadi water 500 ml 3 ctn");
  expect(parts.filter((p) => p.hit).map((p) => p.text)).toEqual(["AL WADI water  500 ml 3 ctn"]);
  expect(parts.map((p) => p.text).join("")).toBe("Hi boss\nAL WADI water  500 ml 3 ctn\nthanks");
});

test("works for Arabic and leaves text alone when the line isn't in it", () => {
  expect(highlightParts("ابي ٣ كرتون ماي", "٣ كرتون ماي").some((p) => p.hit)).toBe(true);
  expect(highlightParts("hello", "(a.b)")).toEqual([{ text: "hello", hit: false }]);
  expect(highlightParts("hello", null)).toEqual([{ text: "hello", hit: false }]);
});
