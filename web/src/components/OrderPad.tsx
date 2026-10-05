import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { Line, LineChange, Me, OrderDetail, Product, Unit } from "../lib/types";
import { api, ApiError } from "../lib/api";
import { keys } from "../lib/hooks";
import { FLAG_TEXT, HOLD_TEXT, money, shortDate, UNIT_LABEL } from "../lib/format";
import { needsCheck, SURE } from "../lib/lines";
import ProductPicker from "./ProductPicker";
import Stamp from "./Stamp";
import "./OrderPad.css";

const isOpen = (o: OrderDetail) => o.status === "review" || o.status === "parsing";

function reasons(l: Line): string[] {
  const out = l.flags.filter((f) => f !== "from_last_order" && FLAG_TEXT[f]).map((f) => FLAG_TEXT[f] ?? f);
  if (l.sku && !l.edited && l.confidence < SURE && !l.flags.includes("unresolved")) out.unshift("Model wasn't sure");
  return out;
}

function unitsFor(p: Product | null): Unit[] {
  if (!p) return ["carton", "pack", "piece"];
  const u: Unit[] = [];
  if (p.carton_size > 1) u.push("carton");
  if (p.pack_size > 0) u.push("pack");
  u.push("piece");
  return u;
}

function packText(p: Product, unit: Unit): string {
  if (unit === "carton") return `carton of ${p.carton_size}`;
  if (unit === "pack") return `pack of ${p.pack_size}`;
  return "single";
}

// ---- one line, read-only or being edited ------------------------------------------------------------------------
function EditLine({ line: l, onCancel, onSave }: { line: Line; onCancel: () => void; onSave: (c: LineChange, oldSku: string | null, p: Product) => void }) {
  const [product, setProduct] = useState<Product | null>(l.product);
  const [qty, setQty] = useState(String(l.qty || 1));
  const [unit, setUnit] = useState<Unit>(l.unit);
  const units = unitsFor(product);
  const q = Number(qty);
  const valid = product !== null && Number.isInteger(q) && q > 0 && units.includes(unit);
  return (
    <li className="pad-line pad-line--editing">
      <form className="pad-edit" onSubmit={(e) => {
        e.preventDefault();
        if (valid && product) onSave({ op: "update", position: l.position, sku: product.id, qty: q, unit }, l.sku, product);
      }} onKeyDown={(e) => e.key === "Escape" && onCancel()}>
        <div className="field pad-edit-qty">
          <label htmlFor={`qty-${l.position}`}>Quantity</label>
          <input id={`qty-${l.position}`} className="input" inputMode="numeric" value={qty} onChange={(e) => setQty(e.target.value.replace(/\D/g, ""))} />
        </div>
        <div className="field">
          <label htmlFor={`unit-${l.position}`}>Unit</label>
          <select id={`unit-${l.position}`} className="input" value={unit} onChange={(e) => setUnit(e.target.value as Unit)}>
            {units.map((u) => <option key={u} value={u}>{product ? packText(product, u) : u}</option>)}
          </select>
        </div>
        <div className="field pad-edit-product">
          <span className="pad-edit-label">Product</span>
          <ProductPicker value={product} onChange={(p) => { setProduct(p); if (!unitsFor(p).includes(unit)) setUnit(unitsFor(p)[0] ?? "piece"); }} autoFocus />
        </div>
        <div className="pad-edit-actions">
          <button className="btn btn-primary" disabled={!valid}>Save line</button>
          <button type="button" className="btn btn-quiet" onClick={onCancel}>Cancel</button>
        </div>
      </form>
      <p className="pad-source" dir="auto">They wrote: “{l.source_text}”</p>
    </li>
  );
}


function LineRow(props: {
  line: Line;
  selected: boolean;
  editing: boolean;
  readOnly: boolean;
  onSelect: () => void;
  onEdit: () => void;
  onCancel: () => void;
  onSave: (c: LineChange, oldSku: string | null, newProduct: Product) => void;
  onDelete: () => void;
}) {
  const { line: l, selected, editing, readOnly } = props;
  const [why, setWhy] = useState(false);
  const check = !readOnly && needsCheck(l);
  if (editing) return <EditLine line={l} onCancel={props.onCancel} onSave={props.onSave} />;

  return (
    <li className={`pad-line ${check ? "pad-line--check" : ""} ${selected ? "is-selected" : ""}`} onMouseEnter={props.onSelect} onFocus={props.onSelect}>
      <div className="pad-row">
        <span className="pad-qty">
          {l.sku ? <>{l.qty} <span className="pad-unit">{UNIT_LABEL[l.unit] ?? l.unit}</span></> : "?"}
        </span>
        <span className="pad-product">
          {l.product ? (
            <>
              <span className="pad-name">{l.product.name_en}</span>
              <span className="pad-sub">
                <span dir="rtl" lang="ar">{l.product.name_ar}</span>
                <span>{l.qty_base} {l.qty_base === 1 ? "unit" : "units"}{l.unit !== "piece" ? `, ${packText(l.product, l.unit)}` : ""}</span>
              </span>
            </>
          ) : (
            <span className="pad-name pad-name--missing">No product matched</span>
          )}
          <span className="pad-source" dir="auto">“{l.source_text}”</span>
          {(check || l.edited) && (
            <span className="pad-reasons">
              {l.edited && <span className="chip">Edited</span>}
              {reasons(l).map((r) => <span key={r} className="chip chip--check">{r}</span>)}
            </span>
          )}
        </span>
        <span className="pad-amount">{l.sku ? money(l.amount_fils) : ""}</span>
        {!readOnly && (
          <span className="pad-actions">
            <button className="btn btn-quiet" onClick={props.onEdit} aria-label={`Edit line ${l.position + 1}`}>Edit</button>
            <button className="btn btn-quiet" onClick={() => setWhy((v) => !v)} aria-expanded={why}>Why?</button>
            <button className="btn btn-quiet btn-danger" onClick={props.onDelete} aria-label={`Remove line ${l.position + 1}`}>Remove</button>
          </span>
        )}
      </div>
      {why && (
        <div className="pad-why">
          <p>{l.why || (l.flags.includes("from_last_order") ? "Copied from their last order." : "Read by the fallback parser, without the model.")}</p>
          {l.candidates.length > 1 && (
            <p className="pad-alts">
              Other matches it considered:{" "}
              {l.candidates.filter((c) => c.id !== l.sku).slice(0, 4).map((c) => (
                <button key={c.id} className="btn btn-quiet pad-alt" onClick={() => props.onSave({ op: "update", position: l.position, sku: c.id, unit: unitsFor(c).includes(l.unit) ? l.unit : unitsFor(c)[0] ?? "piece" }, l.sku, c)}>
                  {c.name_en}
                </button>
              ))}
            </p>
          )}
        </div>
      )}
      {l.flags.includes("out_of_stock") && l.substitutes.length > 0 && !readOnly && (
        <p className="pad-subs">
          Out of stock. In stock instead:{" "}
          {l.substitutes.map((s) => (
            <button key={s.id} className="btn pad-alt" onClick={() => props.onSave({ op: "update", position: l.position, sku: s.id, unit: unitsFor(s).includes(l.unit) ? l.unit : unitsFor(s)[0] ?? "piece" }, l.sku, s)}>
              {s.name_en}
            </button>
          ))}
        </p>
      )}
    </li>
  );
}

// ---- teaching a name after a correction ------------------------------------------------------------------------------
function TeachName({ order, product, sourceText, onClose }: { order: OrderDetail; product: Product; sourceText: string; onClose: () => void }) {
  const guess = sourceText.replace(/[\d٠-٩.]+/g, " ").replace(/\b(ctn|ctns|carton|cartons|pcs|pc|pkt|pack|case|cs|nos|kg|g|ml|l|ltr|x|peti|kartoon)\b/gi, " ").replace(/\s+/g, " ").trim();
  const [term, setTerm] = useState(guess);
  const [msg, setMsg] = useState<string | null>(null);
  async function teach(forShop: boolean) {
    try {
      await api.teach(term, product.id, forShop ? order.customer?.id ?? null : null);
      setMsg(forShop ? `Saved: when ${order.customer?.name ?? "this shop"} writes “${term}” it means ${product.name_en}.` : `Saved for everyone: “${term}” is ${product.name_en.replace(/ \d.*$/, "")}.`);
      setTimeout(onClose, 2500);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Couldn't save the name");
    }
  }
  return (
    <div className="pad-teach" role="region" aria-label="Remember this name">
      {msg ? <p role="status">{msg}</p> : (
        <>
          <label htmlFor="teach-term">Remember that</label>
          <input id="teach-term" className="input" dir="auto" value={term} onChange={(e) => setTerm(e.target.value)} />
          <span>means {product.name_en}?</span>
          <button className="btn" onClick={() => void teach(true)} disabled={term.length < 2}>For this shop</button>
          <button className="btn" onClick={() => void teach(false)} disabled={term.length < 2}>For everyone</button>
          <button className="btn btn-quiet" onClick={onClose}>No</button>
        </>
      )}
    </div>
  );
}

// ---- the pad ------------------------------------------------------------------------------------------------------------
export default function OrderPad({ me, order, loading, onHighlight, onDone }: {
  me: Me;
  order: OrderDetail | null;
  loading: boolean;
  onHighlight: (text: string | null) => void;
  onDone: () => void;
}) {
  const qc = useQueryClient();
  const [selected, setSelected] = useState(0);
  const [editing, setEditing] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [justStamped, setJustStamped] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [teach, setTeach] = useState<{ product: Product; source: string } | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const padRef = useRef<HTMLElement>(null);

  const line = order?.lines[selected];
  useEffect(() => onHighlight(line ? line.source_text : null), [line, onHighlight]);

  const blockers = useMemo(() => {
    if (!order) return [];
    const b: string[] = [];
    if (order.lines.length === 0) b.push("Add at least one line.");
    if (order.lines.some((l) => l.sku === null || l.qty_base <= 0)) b.push("Match every line to a product.");
    if (!order.customer) b.push("This number isn't a known customer.");
    if (order.required_role === "supervisor" && me.role !== "supervisor")
      b.push(order.holds.includes("credit_hold") ? "Over the credit limit: a supervisor confirms this one." : "Large order: a supervisor confirms this one.");
    return b;
  }, [order, me.role]);

  async function apply(changes: LineChange[]) {
    if (!order) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await api.edit(order.id, order.version, changes);
      qc.setQueryData(keys.order(order.id), updated);
      void qc.invalidateQueries({ queryKey: ["orders"] });
      setEditing(null);
      setAdding(false);
    } catch (e) {
      setError(e instanceof ApiError && e.status === 409 ? "Someone else changed this order. It has been reloaded." : e instanceof Error ? e.message : "Couldn't save");
      void qc.invalidateQueries({ queryKey: keys.order(order.id) });
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!order || blockers.length || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.confirm(order.id, order.version);
      setJustStamped(true);
      void qc.invalidateQueries({ queryKey: keys.order(order.id) });
      void qc.invalidateQueries({ queryKey: ["orders"] });
      setTimeout(onDone, 1100);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't confirm");
    } finally {
      setBusy(false);
    }
  }

  async function doReject() {
    if (!order || !reason.trim()) return;
    try {
      await api.reject(order.id, reason.trim());
      void qc.invalidateQueries({ queryKey: keys.order(order.id) });
      void qc.invalidateQueries({ queryKey: ["orders"] });
      setRejecting(false);
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't reject");
    }
  }

  // keyboard: arrows choose a line, e edits it, Enter confirms
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!order || !isOpen(order)) return;
      const t = e.target as HTMLElement;
      if (t.closest("input, textarea, select, button, [role='combobox']") || editing !== null || adding || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "ArrowDown") { e.preventDefault(); setSelected((s) => Math.min(order.lines.length - 1, s + 1)); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setSelected((s) => Math.max(0, s - 1)); }
      else if (e.key === "e") { e.preventDefault(); setEditing(order.lines[selected]?.position ?? null); }
      else if (e.key === "Enter") { e.preventDefault(); void confirm(); }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (loading) return <section className="pad pad--empty"><p className="muted">Opening order…</p></section>;
  if (!order) {
    return (
      <section className="pad pad--empty" aria-label="Order">
        <div className="pad-welcome">
          <h2>Pick an order from the list</h2>
          <p className="muted">Each WhatsApp conversation becomes a draft. Lines in pink need a look; the rest were read with high confidence. Hover a line to see the words it came from.</p>
          <p className="muted"><kbd>j</kbd> <kbd>k</kbd> next and previous order, <kbd>↑</kbd> <kbd>↓</kbd> lines, <kbd>e</kbd> edit, <kbd>Enter</kbd> confirm.</p>
        </div>
      </section>
    );
  }

  const open = isOpen(order);
  const c = order.customer_detail;
  const after = c ? c.balance_fils + order.total_fils : 0;
  const pctUsed = c ? Math.min(100, Math.round((after / c.credit_limit_fils) * 100)) : 0;
  const toCheck = order.lines.filter(needsCheck).length;
  const stamp =
    order.status === "posted" ? <Stamp kind="posted" detail={order.erp_ref ?? undefined} /> :
    order.status === "post_failed" ? <Stamp kind="failed" detail="See ERP & jobs" /> :
    order.status === "rejected" ? <Stamp kind="rejected" /> :
    order.status === "confirmed" || justStamped ? <Stamp kind="confirmed" detail="Sending to ERP" animate={justStamped} /> : null;

  return (
    <section className="pad" aria-label={`Order ${order.ref}`} ref={padRef}>
      <header className="pad-head">
        <div className="pad-title">
          <h2 dir="auto">{c?.name ?? "Unknown number"}</h2>
          <p className="muted">{c ? `${c.contact_name}, ${c.area}. Tier ${c.tier} prices.` : "Link this number to a customer before confirming."}</p>
        </div>
        <p className="pad-ref" aria-label="Order number">No. {order.ref}</p>
      </header>
      {c && (
        <div className={`pad-credit ${order.holds.includes("credit_hold") ? "pad-credit--over" : ""}`}>
          <div className="pad-credit-bar" aria-hidden="true"><span style={{ width: `${pctUsed}%` }} /></div>
          <p>
            Credit: AED {money(c.balance_fils)} owed + this order {money(order.total_fils)} of a {money(c.credit_limit_fils)} limit
            {order.holds.includes("credit_hold") ? <strong>. {HOLD_TEXT.credit_hold}.</strong> : null}
          </p>
        </div>
      )}
      {order.notes.map((n) => <p key={n} className="pad-note">{n}</p>)}
      {open && toCheck > 0 && <p className="pad-summary">{toCheck} of {order.lines.length} {order.lines.length === 1 ? "line needs" : "lines need"} a look.</p>}
      {open && toCheck === 0 && order.lines.length > 0 && <p className="pad-summary pad-summary--ok">Every line was read with high confidence. Check it over and confirm.</p>}

      <ol className="pad-lines" aria-label="Order lines">
        {order.lines.map((l, i) => (
          <LineRow key={`${order.id}-${l.position}-${l.sku}`} line={l} selected={i === selected} editing={editing === l.position} readOnly={!open}
            onSelect={() => setSelected(i)} onEdit={() => setEditing(l.position)} onCancel={() => setEditing(null)}
            onDelete={() => void apply([{ op: "delete", position: l.position }])}
            onSave={(ch, oldSku, p) => {
              void apply([ch]).then(() => {
                if (oldSku !== p.id && l.source_text && !l.source_text.startsWith("(") && !l.flags.includes("from_last_order")) setTeach({ product: p, source: l.source_text });
              });
            }} />
        ))}
        {adding && <AddLine onAdd={(ch) => void apply([ch])} onCancel={() => setAdding(false)} />}
      </ol>
      {open && !adding && <button className="btn btn-quiet pad-add" onClick={() => setAdding(true)}>Add a line</button>}
      {teach && <TeachName order={order} product={teach.product} sourceText={teach.source} onClose={() => setTeach(null)} />}

      <footer className="pad-foot">
        {stamp}
        <p className="pad-total">
          <span className="muted">Total</span> AED {money(order.total_fils)}
        </p>
        {error && <p className="error-text" role="alert">{error}</p>}
        {open && (
          <div className="pad-confirm">
            {blockers.length > 0 && <p className="pad-blockers">{blockers.join(" ")}</p>}
            {rejecting ? (
              <form className="pad-reject" onSubmit={(e) => { e.preventDefault(); void doReject(); }}>
                <label htmlFor="reject-reason" className="visually-hidden">Reason</label>
                <input id="reject-reason" className="input" autoFocus placeholder="Why? The customer gets a 'we'll call you' message." value={reason} onChange={(e) => setReason(e.target.value)} />
                <button className="btn btn-danger" disabled={!reason.trim()}>Reject order</button>
                <button type="button" className="btn btn-quiet" onClick={() => setRejecting(false)}>Cancel</button>
              </form>
            ) : (
              <>
                <button className="btn btn-quiet btn-danger" onClick={() => setRejecting(true)}>Reject…</button>
                <button className="btn btn-primary pad-confirm-btn" disabled={blockers.length > 0 || busy} onClick={() => void confirm()}>
                  Confirm order <kbd>Enter</kbd>
                </button>
              </>
            )}
          </div>
        )}
        <div className="pad-meta">
          {order.recent_orders.length > 0 && (
            <p className="muted">Recent: {order.recent_orders.map((r) => `${shortDate(r.date)} (${r.lines} lines, AED ${money(r.total_fils)})`).join(", ")}</p>
          )}
          <p className="muted">
            Read by {order.parsed_by === "fallback" ? "the fallback parser" : order.parsed_by} for ${order.parse_cost_usd.toFixed(3)}.{" "}
            <button className="btn btn-quiet" onClick={() => setShowHistory((v) => !v)} aria-expanded={showHistory}>History</button>
          </p>
          {showHistory && <History refNo={order.ref} />}
        </div>
      </footer>
    </section>
  );
}

function AddLine({ onAdd, onCancel }: { onAdd: (c: LineChange) => void; onCancel: () => void }) {
  const [product, setProduct] = useState<Product | null>(null);
  const [qty, setQty] = useState("1");
  const [unit, setUnit] = useState<Unit>("carton");
  const units = unitsFor(product);
  const q = Number(qty);
  return (
    <li className="pad-line pad-line--editing">
      <form className="pad-edit" onSubmit={(e) => { e.preventDefault(); if (product && q > 0) onAdd({ op: "add", sku: product.id, qty: q, unit }); }}
        onKeyDown={(e) => e.key === "Escape" && onCancel()}>
        <div className="field pad-edit-qty">
          <label htmlFor="add-qty">Quantity</label>
          <input id="add-qty" className="input" inputMode="numeric" value={qty} onChange={(e) => setQty(e.target.value.replace(/\D/g, ""))} />
        </div>
        <div className="field">
          <label htmlFor="add-unit">Unit</label>
          <select id="add-unit" className="input" value={unit} onChange={(e) => setUnit(e.target.value as Unit)}>
            {units.map((u) => <option key={u} value={u}>{product ? packText(product, u) : u}</option>)}
          </select>
        </div>
        <div className="field pad-edit-product">
          <span className="pad-edit-label">Product</span>
          <ProductPicker value={null} onChange={(p) => { setProduct(p); if (!unitsFor(p).includes(unit)) setUnit(unitsFor(p)[0] ?? "piece"); }} autoFocus />
        </div>
        <div className="pad-edit-actions">
          <button className="btn btn-primary" disabled={!product || !(q > 0)}>Add line</button>
          <button type="button" className="btn btn-quiet" onClick={onCancel}>Cancel</button>
        </div>
      </form>
    </li>
  );
}

function History({ refNo }: { refNo: string }) {
  const q = useQuery({ queryKey: ["audit", refNo], queryFn: () => api.audit(refNo) });
  const label: Record<string, string> = { parsed: "Read from WhatsApp", edited: "Edited", confirmed: "Confirmed", posted_to_erp: "Posted to the ERP",
    erp_rejected: "Rejected by the ERP", erp_post_failed: "ERP posting failed", rejected: "Rejected" };
  if (!q.data) return null;
  return (
    <ol className="pad-history">
      {q.data.map((e, i) => (
        <li key={i}>
          <time dateTime={e.at}>{new Date(e.at).toLocaleTimeString("en-GB", { timeZone: "Asia/Dubai", hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time>{" "}
          {label[e.action] ?? e.action} by {e.actor}{e.note ? `: ${e.note}` : ""}
        </li>
      ))}
    </ol>
  );
}
