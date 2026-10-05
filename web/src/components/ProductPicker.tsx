import { useEffect, useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Product } from "../lib/types";
import { api } from "../lib/api";

/** An accessible combobox (ARIA 1.2 pattern) over the catalogue: type a name, size or barcode. */
export default function ProductPicker({ value, onChange, autoFocus }: { value: Product | null; onChange: (p: Product) => void; autoFocus?: boolean }) {
  const id = useId();
  const [text, setText] = useState(value ? `${value.name_en}` : "");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  useEffect(() => {
    const t = setTimeout(() => setQ(text), 150);
    return () => clearTimeout(t);
  }, [text]);
  const results = useQuery({ queryKey: ["products", q], queryFn: () => api.products(q), enabled: open && q.trim().length > 0, staleTime: 60_000 });
  const items = results.data ?? [];

  function pick(p: Product) {
    onChange(p);
    setText(p.name_en);
    setOpen(false);
  }

  return (
    <div className="picker">
      <input
        id={`${id}-input`}
        className="input picker-input"
        role="combobox"
        aria-label="Product"
        aria-expanded={open && items.length > 0}
        aria-controls={`${id}-list`}
        aria-autocomplete="list"
        aria-activedescendant={open && items[active] ? `${id}-opt-${active}` : undefined}
        autoFocus={autoFocus}
        value={text}
        placeholder="Search name, size or barcode"
        onChange={(e) => {
          setText(e.target.value);
          setOpen(true);
          setActive(0);
        }}
        onFocus={(e) => e.target.select()}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setOpen(true);
            setActive((a) => Math.min(items.length - 1, a + 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActive((a) => Math.max(0, a - 1));
          } else if (e.key === "Enter" && open && items[active]) {
            e.preventDefault();
            e.stopPropagation();
            pick(items[active]);
          } else if (e.key === "Escape" && open) {
            e.stopPropagation();
            setOpen(false);
          }
        }}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
      />
      {open && items.length > 0 && (
        <ul className="picker-list" role="listbox" id={`${id}-list`}>
          {items.map((p, i) => (
            <li key={p.id} id={`${id}-opt-${i}`} role="option" aria-selected={i === active}
              className={`picker-opt ${i === active ? "is-active" : ""}`} onMouseDown={(e) => e.preventDefault()} onClick={() => pick(p)}>
              <span>{p.name_en}</span>
              <span className="picker-sub">
                <span dir="rtl" lang="ar">{p.name_ar}</span>
                <span>{p.stock_on_hand > 0 ? `${p.stock_on_hand} in stock` : "Out of stock"}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
