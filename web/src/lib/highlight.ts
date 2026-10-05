/** Split `text` into parts, marking where `needle` occurs (case-insensitive, whitespace-tolerant).
 *  Used to show which words of a message a draft line was read from. */
export interface Part {
  text: string;
  hit: boolean;
}

const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

export function highlightParts(text: string, needle: string | null): Part[] {
  const n = (needle ?? "").trim();
  if (!n || n.length < 2) return [{ text, hit: false }];
  const pattern = n.split(/\s+/).map(esc).join("\\s+");
  const re = new RegExp(pattern, "iu");
  const m = re.exec(text);
  if (!m) return [{ text, hit: false }];
  const out: Part[] = [];
  if (m.index > 0) out.push({ text: text.slice(0, m.index), hit: false });
  out.push({ text: m[0], hit: true });
  if (m.index + m[0].length < text.length) out.push({ text: text.slice(m.index + m[0].length), hit: false });
  return out;
}
