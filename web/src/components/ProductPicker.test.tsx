import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ProductPicker from "./ProductPicker";

const products = [
  { id: "SL-1", name_en: "Mirage Orange 330 ml can", name_ar: "ميراج برتقال", size_label: "330 ml can", pack_size: 6, carton_size: 24, stock_on_hand: 100, family: "mirage_orange" },
  { id: "SL-2", name_en: "Mirage Orange 500 ml bottle", name_ar: "ميراج برتقال", size_label: "500 ml bottle", pack_size: 6, carton_size: 24, stock_on_hand: 0, family: "mirage_orange" },
];

test("is a keyboard-usable combobox", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(products), { status: 200 })));
  const onChange = vi.fn();
  render(<QueryClientProvider client={new QueryClient()}><ProductPicker value={null} onChange={onChange} /></QueryClientProvider>);
  const box = screen.getByRole("combobox", { name: "Product" });
  await userEvent.type(box, "mirage");
  await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(2));
  expect(screen.getByText("Out of stock")).toBeInTheDocument();
  await userEvent.keyboard("{ArrowDown}{Enter}");
  expect(onChange).toHaveBeenCalledWith(products[1]);
  vi.unstubAllGlobals();
});
