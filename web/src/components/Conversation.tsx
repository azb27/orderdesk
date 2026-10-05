import { useState } from "react";
import type { ChatMessage, OrderDetail } from "../lib/types";
import { clock } from "../lib/format";
import { highlightParts } from "../lib/highlight";
import "./Conversation.css";

function Bubble({ m, highlight, onZoom }: { m: ChatMessage; highlight: string | null; onZoom: (src: string) => void }) {
  const src = `/api/media/${m.id}`;
  return (
    <li className={`bubble bubble--${m.direction}`}>
      {m.type === "image" && m.has_media ? (
        <button className="bubble-photo" onClick={() => onZoom(src)} aria-label="Open the photo full size">
          <img src={src} alt="Photo of a handwritten order list" loading="lazy" />
        </button>
      ) : null}
      {m.type === "audio" ? <p className="muted">Voice note: listen in WhatsApp and key it by hand.</p> : null}
      {m.text ? (
        <p dir="auto" className="bubble-text">
          {highlightParts(m.text, m.direction === "in" ? highlight : null).map((p, i) =>
            p.hit ? <mark key={i}>{p.text}</mark> : <span key={i}>{p.text}</span>,
          )}
        </p>
      ) : null}
      <time className="bubble-time" dateTime={m.at}>{clock(m.at)}</time>
    </li>
  );
}

export default function Conversation({ order, highlight }: { order: OrderDetail | null; highlight: string | null }) {
  const [zoom, setZoom] = useState<string | null>(null);
  if (!order) return <section className="conv conv--empty" aria-label="Conversation" />;
  const c = order.customer_detail;
  return (
    <section className="conv" aria-label="WhatsApp conversation">
      <header className="conv-head">
        <h2 dir="auto">{c ? c.contact_name : "Unknown number"}</h2>
        <p className="muted">{c ? `${c.name}, ${c.area}` : "Not in the customer list"}</p>
      </header>
      <ol className="conv-thread">
        {order.messages.map((m) => (
          <Bubble key={m.id} m={m} highlight={highlight} onZoom={setZoom} />
        ))}
      </ol>
      {zoom && (
        <div className="conv-zoom" role="dialog" aria-modal="true" aria-label="Photo" onClick={() => setZoom(null)}
          onKeyDown={(e) => e.key === "Escape" && setZoom(null)}>
          <img src={zoom} alt="Handwritten order list, full size" />
          <button className="btn" autoFocus onClick={() => setZoom(null)}>Close</button>
        </div>
      )}
    </section>
  );
}
