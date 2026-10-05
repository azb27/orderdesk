import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router";
import type { Me } from "../lib/types";
import { useLiveUpdates, useOrder, useOrders } from "../lib/hooks";
import Topbar from "../components/Topbar";
import Queue from "../components/Queue";
import Conversation from "../components/Conversation";
import OrderPad from "../components/OrderPad";
import Phone from "../components/Phone";
import "./DeskPage.css";

const TABS = [
  { key: "open", label: "To check" },
  { key: "confirmed", label: "Confirmed" },
  { key: "posted", label: "In ERP" },
  { key: "post_failed", label: "ERP failed" },
  { key: "rejected", label: "Rejected" },
];

export default function DeskPage({ me }: { me: Me }) {
  const params = useParams();
  const navigate = useNavigate();
  const [tab, setTab] = useState("open");
  const [phoneOpen, setPhoneOpen] = useState(() => localStorageGet("od.phone") === "1");
  const [highlight, setHighlight] = useState<string | null>(null);
  const live = useLiveUpdates(true);
  const orders = useOrders(tab);
  const selectedId = params.id ? Number(params.id) : null;
  const order = useOrder(selectedId);
  const list = useMemo(() => orders.data ?? [], [orders.data]);

  const select = useCallback((id: number) => navigate(`/orders/${id}`), [navigate]);

  // j / k move through the queue from anywhere outside a text field
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement;
      if (t.closest("input, textarea, select, [role='combobox'], [contenteditable='true']") || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key !== "j" && e.key !== "k") return;
      e.preventDefault();
      const i = list.findIndex((o) => o.id === selectedId);
      const next = e.key === "j" ? Math.min(list.length - 1, i + 1) : Math.max(0, i - 1);
      const o = list[next === -1 ? 0 : next];
      if (o) select(o.id);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [list, selectedId, select]);

  // after confirming, move to the next order still waiting
  const onDone = useCallback(() => {
    const rest = list.filter((o) => o.id !== selectedId && (o.status === "review" || o.status === "parsing"));
    if (rest[0]) select(rest[0].id);
  }, [list, selectedId, select]);

  function togglePhone() {
    setPhoneOpen((v) => {
      localStorageSet("od.phone", v ? "0" : "1");
      return !v;
    });
  }

  return (
    <div className={`desk ${phoneOpen ? "desk--phone" : ""}`}>
      <Topbar me={me} live={live} phoneOpen={phoneOpen} onTogglePhone={togglePhone} />
      <nav className="desk-tabs" aria-label="Order lists">
        {TABS.map((t) => (
          <button key={t.key} className={`desk-tab ${tab === t.key ? "is-active" : ""}`} aria-pressed={tab === t.key} onClick={() => setTab(t.key)}>
            {t.label}
            {tab === t.key && orders.data ? <span className="desk-tab-count">{orders.data.length}</span> : null}
          </button>
        ))}
      </nav>
      <Queue orders={list} loading={orders.isPending} selectedId={selectedId} onSelect={select} tab={tab} />
      <Conversation order={order.data ?? null} highlight={highlight} />
      <OrderPad key={selectedId ?? "none"} me={me} order={order.data ?? null} loading={selectedId !== null && order.isPending} onHighlight={setHighlight} onDone={onDone} />
      {phoneOpen && <Phone onClose={togglePhone} />}
    </div>
  );
}

function localStorageGet(k: string): string | null {
  try {
    return window.localStorage.getItem(k);
  } catch {
    return null;
  }
}
function localStorageSet(k: string, v: string): void {
  try {
    window.localStorage.setItem(k, v);
  } catch {
    /* private mode: the toggle just won't be remembered */
  }
}
