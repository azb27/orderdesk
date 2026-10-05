import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Queue from "./Queue";
import type { OrderSummary } from "../lib/types";

const order = (over: Partial<OrderSummary>): OrderSummary => ({
  id: 1, ref: "SL-1", status: "review", customer: { id: "C1", name: "Al Noor Grocery", area: "Deira" }, lines: 4, needs_attention: 2,
  total_fils: 120050, holds: [], parsed_by: "claude-sonnet-5", created_at: "2026-10-05T08:00:00Z", age_minutes: 12, erp_ref: null,
  required_role: "order_taker", ...over,
});

test("shows what needs a look, credit holds and fallback reads", async () => {
  const onSelect = vi.fn();
  render(<Queue tab="open" loading={false} selectedId={null} onSelect={onSelect}
    orders={[order({}), order({ id: 2, customer: null, holds: ["credit_hold", "needs_review"], parsed_by: "fallback", needs_attention: 0 })]} />);
  expect(screen.getByText("2 to check")).toBeInTheDocument();
  expect(screen.getByText("Over credit limit")).toBeInTheDocument();
  expect(screen.queryByText("Needs a look")).not.toBeInTheDocument(); // implied by the pink count, not repeated
  expect(screen.getByText("Read without the model")).toBeInTheDocument();
  expect(screen.getByText("Unknown number")).toBeInTheDocument();
  await userEvent.click(screen.getByText("Al Noor Grocery"));
  expect(onSelect).toHaveBeenCalledWith(1);
});

test("an empty queue tells you what to do", () => {
  render(<Queue tab="open" loading={false} selectedId={null} onSelect={() => undefined} orders={[]} />);
  expect(screen.getByText(/send one from the retailer phone/)).toBeInTheDocument();
});
