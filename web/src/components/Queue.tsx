import type { OrderSummary } from "../lib/types";
import { age, HOLD_TEXT, money } from "../lib/format";
import "./Queue.css";

const EMPTY: Record<string, string> = {
  open: "Nothing to check. New WhatsApp orders appear here as they're read; send one from the retailer phone to try it.",
  confirmed: "No confirmed orders waiting for the ERP.",
  posted: "No orders posted to the ERP in this list yet.",
  post_failed: "No ERP failures.",
  rejected: "No rejected orders.",
};

export default function Queue({ orders, loading, selectedId, onSelect, tab }: {
  orders: OrderSummary[];
  loading: boolean;
  selectedId: number | null;
  onSelect: (id: number) => void;
  tab: string;
}) {
  return (
    <section className="queue" aria-label="Orders">
      {loading && <p className="queue-empty muted">Loading…</p>}
      {!loading && orders.length === 0 && <p className="queue-empty muted">{EMPTY[tab]}</p>}
      <ol className="queue-list">
        {orders.map((o) => (
          <li key={o.id}>
            <button className={`queue-item ${o.id === selectedId ? "is-selected" : ""} ${o.holds.includes("credit_hold") ? "has-credit" : ""}`}
              aria-current={o.id === selectedId ? "true" : undefined} onClick={() => onSelect(o.id)}>
              <span className="queue-row">
                <span className="queue-name" dir="auto">{o.customer?.name ?? "Unknown number"}</span>
                <span className="queue-age">{age(o.age_minutes)}</span>
              </span>
              <span className="queue-row queue-meta">
                <span>
                  {o.lines} {o.lines === 1 ? "line" : "lines"}
                  {o.needs_attention > 0 && o.status === "review" ? <span className="queue-attn">{o.needs_attention} to check</span> : null}
                </span>
                <span>AED {money(o.total_fils)}</span>
              </span>
              {(o.holds.length > 0 || o.parsed_by === "fallback") && (
                <span className="queue-row queue-holds">
                  {o.holds.filter((h) => h !== "needs_review").map((h) => (
                    <span key={h} className={`chip chip--${h}`}>{HOLD_TEXT[h] ?? h}</span>
                  ))}
                  {o.parsed_by === "fallback" && <span className="chip">Read without the model</span>}
                </span>
              )}
            </button>
          </li>
        ))}
      </ol>
      <p className="queue-hint muted">
        <kbd>j</kbd> <kbd>k</kbd> to move between orders
      </p>
    </section>
  );
}
