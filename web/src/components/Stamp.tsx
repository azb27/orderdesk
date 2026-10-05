import "./Stamp.css";

/** The rubber stamp on the order pad: the one piece of motion in the app, played when an order is confirmed. */
export default function Stamp({ kind, detail, animate }: { kind: "confirmed" | "posted" | "failed" | "rejected"; detail?: string; animate?: boolean }) {
  const word = { confirmed: "Confirmed", posted: "In ERP", failed: "ERP failed", rejected: "Rejected" }[kind];
  return (
    <div className={`stamp stamp--${kind} ${animate ? "stamp--animate" : ""}`} role="status">
      <span className="stamp-word">{word}</span>
      {detail ? <span className="stamp-detail">{detail}</span> : null}
    </div>
  );
}
