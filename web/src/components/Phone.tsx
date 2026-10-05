import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { keys } from "../lib/hooks";
import { clock } from "../lib/format";
import "./Phone.css";

const SAMPLES: Record<string, { label: string; text: string }[]> = {
  en: [
    { label: "Shop English", text: "Hi boss\n3 ctn al wadi 500ml\nkola zero 2.25 x 2 ctn\n6 pcs sunflower oil 1.8\ntks" },
    { label: "Repeat with a change", text: "same as last order but add 2 ctn tomato paste 400g" },
  ],
  roman: [
    { label: "Roman Urdu", text: "salam bhai\nchawal basmati 5 kilo 2 bori\ncheeni 1 kilo 1 peti\nwafers masala 45 gram 2 petti\nshukriya" },
    { label: "Repeat with a change", text: "pichla order same bhejo lekin doodh nahi chahiye" },
  ],
  ar: [
    { label: "Arabic", text: "السلام عليكم\nنبي بكرة:\nماي نص لتر ٣ كراتين\nلبن قليل الدسم لتر كرتون\nشكرا" },
    { label: "Repeat with a change", text: "نفس الطلب الماضي بس زيد كرتون معجون طماطم ٤٠٠" },
  ],
  arabizi: [
    { label: "Arabizi", text: "salam\nabi 2 kartoon mai 1.5\nw 1 kartoon zabadi kamil 170\nyesalmo" },
    { label: "Repeat with a change", text: "nafs el talab bs zeed 1 kartoon sukkar 2 kilo" },
  ],
};
const PHOTOS = ["/samples/list-1.jpg", "/samples/list-2.jpg"];

export default function Phone({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const customers = useQuery({ queryKey: ["demo-customers"], queryFn: api.demoCustomers, staleTime: Infinity });
  const [chosen, setPhone] = useState<string>("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLLIElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const phone = chosen || customers.data?.[0]?.phone || "";
  const thread = useQuery({ queryKey: keys.thread(phone), queryFn: () => api.thread(phone), enabled: !!phone, refetchInterval: 5_000 });
  const cust = customers.data?.find((c) => c.phone === phone);
  const samples = SAMPLES[cust?.language ?? "en"] ?? SAMPLES.en ?? [];
  useEffect(() => endRef.current?.scrollIntoView({ block: "end" }), [thread.data]);

  async function send(body: string, image?: File) {
    if (!phone || (!body.trim() && !image)) return;
    setBusy(true);
    setError(null);
    try {
      await api.sendAsRetailer(phone, body, image);
      setText("");
      void qc.invalidateQueries({ queryKey: keys.thread(phone) });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't send");
    } finally {
      setBusy(false);
    }
  }

  async function sendPhoto(url: string) {
    const blob = await (await fetch(url)).blob();
    await send("", new File([blob], "list.jpg", { type: "image/jpeg" }));
  }

  return (
    <aside className="phone" aria-label="Retailer phone (demo)">
      <div className="phone-head">
        <h2>Retailer phone</h2>
        <button className="btn btn-quiet" onClick={onClose} aria-label="Close the retailer phone">Close</button>
      </div>
      <p className="phone-explain muted">
        Write as one of Saffron Lane's shops. Messages go through the same signed WhatsApp webhook a real phone would use, and replies come back here.
      </p>
      <div className="field phone-who">
        <label htmlFor="phone-customer">Sending as</label>
        <select id="phone-customer" className="input" value={phone} onChange={(e) => setPhone(e.target.value)}>
          {customers.data?.map((c) => (
            <option key={c.id} value={c.phone}>{c.contact_name}, {c.name}</option>
          ))}
        </select>
      </div>
      <div className="phone-screen">
        <ol className="phone-thread">
          {thread.data?.length === 0 && <li className="muted phone-empty">No messages yet. Try a sample below.</li>}
          {thread.data?.map((m) => (
            <li key={m.id} className={`pbubble pbubble--${m.direction === "in" ? "me" : "them"}`}>
              {m.type === "image" ? <p className="muted">Photo sent</p> : null}
              {m.text ? <p dir="auto">{m.text}</p> : null}
              <time dateTime={m.at}>{clock(m.at)}</time>
            </li>
          ))}
          <li ref={endRef} aria-hidden="true" />
        </ol>
        <form className="phone-compose" onSubmit={(e) => { e.preventDefault(); void send(text); }}>
          <label htmlFor="phone-text" className="visually-hidden">Message</label>
          <textarea id="phone-text" className="input" dir="auto" rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder="Type an order the way a shop would" />
          <div className="phone-actions">
            <button type="button" className="btn btn-quiet" onClick={() => fileRef.current?.click()}>Attach photo</button>
            <input ref={fileRef} type="file" accept="image/jpeg,image/png" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) void send(text, f); e.target.value = ""; }} />
            <button className="btn btn-primary" disabled={busy || !text.trim()}>Send</button>
          </div>
        </form>
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}
      <div className="phone-samples">
        <p className="muted">Samples</p>
        {samples.map((s) => (
          <button key={s.label} className="btn" onClick={() => setText(s.text)}>{s.label}</button>
        ))}
        {PHOTOS.map((p, i) => (
          <button key={p} className="btn" disabled={busy} onClick={() => void sendPhoto(p)}>Send handwritten list {i + 1}</button>
        ))}
      </div>
    </aside>
  );
}
