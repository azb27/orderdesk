"""The order parser: extract (model) → retrieve (code) → resolve (model) → build (code) → confidence (code).

    parse_conversation(messages, phone, models) -> ParseResult

Model outputs are validated against their schema and the candidate lists. Anything invalid is rejected
(the line becomes unresolved), never repaired.
"""

from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from rapidfuzz import fuzz

from orderdesk import config
from orderdesk.parse.build import Draft, Resolved, build_draft
from orderdesk.parse.confidence import score_lines
from orderdesk.parse.llm import Meter, ToolModel
from orderdesk.parse.normalize import norm
from orderdesk.parse.prompts import EXTRACT_SYSTEM, EXTRACT_TOOL, RESOLVE_SYSTEM, resolve_tool
from orderdesk.parse.retrieve import Candidate, all_skus, candidates
from orderdesk.parse.world import World, world

MEDIA = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


@dataclass
class ParseResult:
    draft: Draft
    extraction: dict
    resolutions: list[dict]
    meter: Meter
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"draft": self.draft.to_dict(), "extraction": self.extraction, "resolutions": self.resolutions,
                "meter": asdict(self.meter), "errors": self.errors}  # fmt: skip


def _image_block(ref: str) -> dict:
    p = Path(ref)
    if not p.is_absolute():
        p = config.EVAL / ref
    data = base64.standard_b64encode(p.read_bytes()).decode()
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": MEDIA[p.suffix.lower()], "data": data},
    }


def extraction_content(messages: list[dict], customer: dict | None) -> list[dict]:
    who = (f"Customer: {customer['name']} ({customer['type']}, {customer['area']}). "
           if customer else "Customer: unknown number. ")  # fmt: skip
    content: list[dict] = [{"type": "text", "text": who + f"{len(messages)} message(s), oldest first."}]
    for i, m in enumerate(messages):
        content.append({"type": "text", "text": f"--- message {i} ({m.get('ts', '')}) ---"})
        if m.get("type") == "image" and m.get("image_bytes"):
            data = base64.standard_b64encode(m["image_bytes"]).decode()
            block = {"type": "base64", "media_type": m.get("media_type", "image/jpeg"), "data": data}
            content.append({"type": "image", "source": block})
            if m.get("caption"):
                content.append({"type": "text", "text": f"caption: {m['caption']}"})
        elif m.get("type") == "image":
            content.append(_image_block(m["image"]))
            if m.get("caption"):
                content.append({"type": "text", "text": f"caption: {m['caption']}"})
        else:
            content.append({"type": "text", "text": m.get("text", "")})
    return content


def validate_extraction(x: dict, n_messages: int) -> tuple[dict, list[str]]:
    errs: list[str] = []
    intent = x.get("intent")
    if intent not in ("order", "repeat_last_order", "not_order"):
        return {"intent": "order", "lines": []}, [f"bad intent {intent!r}"]
    lines = []
    for i, ln in enumerate(x.get("lines") or []):
        if not isinstance(ln, dict) or not str(ln.get("product") or "").strip():
            errs.append(f"line {i}: missing product")
            continue
        unit = ln.get("unit")
        if unit not in ("carton", "pack", "piece", None):
            errs.append(f"line {i}: bad unit {unit!r}")
            unit = None
        q = ln.get("quantity")
        if q is not None and (not isinstance(q, int | float) or q <= 0):
            errs.append(f"line {i}: bad quantity {q!r}")
            q = None
        lines.append({"message": min(max(int(ln.get("message") or 0), 0), n_messages - 1), "source": str(ln.get("source") or ""),
                      "product": str(ln["product"]), "size": ln.get("size") or None, "quantity": q, "unit": unit,
                      "action": ln.get("action") if ln.get("action") in ("add", "remove", "set") else "add"})  # fmt: skip
    return {
        "intent": intent,
        "lines": lines,
        "ignored": x.get("ignored") or [],
        "question": x.get("question"),
    }, errs


def _unusable(raw: dict, ext: dict, errors: list[str]) -> bool:
    """The answer can't be used: no valid intent, or it had lines and none survived validation."""
    bad_intent = any(e.startswith("bad intent") for e in errors)
    return bad_intent or (bool(raw.get("lines")) and not ext["lines"])


def _nickname_candidates(w: World, customer: dict | None, source: str, product: str) -> list[Candidate]:
    out = []
    for nick, sku in (customer or {}).get("nicknames", {}).items():
        if max(fuzz.partial_ratio(norm(nick), norm(source)), fuzz.ratio(norm(nick), norm(product))) >= 90:
            out.append(Candidate(sku, w.skus[sku]["family"], 100.0, True, True, True, False, 0, 200.0))
    return out


def _describe(w: World, c: Candidate, customer: dict | None) -> str:
    s = w.skus[c.sku]
    pack = f"carton = {s['carton_size']}"
    if s["pack_size"]:
        pack += f", pack = {s['pack_size']}"
    tags = []
    usual = w.usual(customer["id"]).get(c.sku) if customer else None
    if usual:
        tags.append(f"usual: {usual.qty} {usual.unit}, ordered {usual.times}x")
    if c.score >= 200:
        nick = next(n for n, x in customer["nicknames"].items() if x == c.sku)  # type: ignore[index]
        tags.append(f"customer calls this '{nick}'")
    return f"{c.sku} | {s['name_en']} | {s['name_ar']} | {pack}" + (f" | {'; '.join(tags)}" if tags else "")


def parse_conversation(messages: list[dict], phone: str, extract_model: ToolModel, resolve_model: ToolModel,
                       mode: str = "retrieval", w: World | None = None) -> ParseResult:  # fmt: skip
    w = w or world()
    meter = Meter()
    customer = w.customer_by_phone(phone)
    content = extraction_content(messages, customer)
    raw, usage = extract_model.call(EXTRACT_SYSTEM, content, EXTRACT_TOOL)
    meter.add(usage)
    ext, errors = validate_extraction(raw, len(messages))
    if _unusable(raw, ext, errors):
        # One retry with the reason, never a repair: a second invalid answer leaves the order for a person.
        nudge = {"type": "text", "text": "Your record_order call was invalid (" + "; ".join(errors[:3]) + "). "
                 "Call record_order again with intent set and every line's product filled in."}  # fmt: skip
        raw2, usage = extract_model.call(EXTRACT_SYSTEM, [*content, nudge], EXTRACT_TOOL)
        meter.add(usage)
        ext2, errors2 = validate_extraction(raw2, len(messages))
        errors = [*errors, "extraction retried once", *errors2]
        if not _unusable(raw2, ext2, errors2):
            ext = ext2
    if ext["intent"] == "not_order" or not ext["lines"]:
        draft = build_draft(w, customer, ext["intent"], [], repeat_last=ext["intent"] == "repeat_last_order")
        return ParseResult(draft, ext, [], meter, errors)
    # retrieve candidates per line
    per_line: list[list[Candidate]] = []
    for ln in ext["lines"]:
        cands = (
            all_skus(w, customer)
            if mode == "all"
            else candidates(w, customer, ln["source"], ln["product"], ln["size"])
        )
        nicks = _nickname_candidates(w, customer, ln["source"], ln["product"])
        seen = {c.sku for c in nicks}
        per_line.append(nicks + [c for c in cands if c.sku not in seen])
    # resolve
    blocks = []
    limit = 10_000 if mode == "all" else 40
    if mode == "all":  # ablation: no retrieval; the whole catalogue once, every id allowed for every line
        blocks.append(
            "catalogue (candidates for every line):\n"
            + "\n".join("  " + _describe(w, c, customer) for c in per_line[0] if c.score < 200)
        )
    for i, (ln, cands) in enumerate(zip(ext["lines"], per_line, strict=True)):
        head = f"line {i}: wrote {ln['source']!r}; reads as: {ln['product']}; size written: {ln['size']}"
        if mode == "all":
            nick = [c for c in cands if c.score >= 200]
            blocks.append(
                head
                + (
                    "\nnickname match:\n" + "\n".join("  " + _describe(w, c, customer) for c in nick)
                    if nick
                    else ""
                )
            )
        else:
            listing = "\n".join("  " + _describe(w, c, customer) for c in cands[:limit])
            blocks.append(f"{head}\ncandidates:\n{listing}")
    who = f"Customer: {customer['name']} ({customer['type']})." if customer else "Customer: unknown."
    ids = sorted({c.sku for cands in per_line for c in cands[:limit]})
    raw_r, usage = resolve_model.call(
        RESOLVE_SYSTEM, [{"type": "text", "text": who + "\n\n" + "\n\n".join(blocks)}], resolve_tool(ids)
    )
    meter.add(usage)
    choices = {}
    for ch in raw_r.get("choices") or []:
        if isinstance(ch, dict) and isinstance(ch.get("line"), int):
            choices[ch["line"]] = ch
    resolved: list[Resolved] = []
    resolutions: list[dict] = []
    for i, (ln, cands) in enumerate(zip(ext["lines"], per_line, strict=True)):
        ch = choices.get(i, {})
        sku = ch.get("sku")
        allowed = {c.sku for c in cands[:limit]}
        if sku not in allowed:
            if sku not in (None, "NONE"):
                errors.append(f"line {i}: chose {sku} which was not a candidate; rejected")
            sku = None
        chosen = next((c for c in cands if c.sku == sku), None)
        size_from_history = False
        if chosen and ln["size"] is None and ln["action"] != "remove" and customer and chosen.score < 200:
            # No size written and they only ever buy one size of this product: that size, as a person would.
            fam = w.skus[chosen.sku]["family"]
            mine = [k for k in w.usual(customer["id"]) if w.skus[k]["family"] == fam]
            if len(mine) == 1 and mine[0] != chosen.sku and mine[0] in allowed:
                sku, size_from_history = mine[0], True
                chosen = next(c for c in cands if c.sku == sku)
        feats = {"rank": chosen.rank if chosen else 0, "family_score": chosen.family_score if chosen else 0.0,
                 "alias_exact": bool(chosen and chosen.alias_exact), "in_history": bool(chosen and chosen.in_history),
                 "family_in_history": bool(chosen and chosen.family_in_history), "size_match": bool(chosen and chosen.size_match),
                 "nickname": bool(chosen and chosen.score >= 200), "n_candidates": len(cands),
                 "size_given": ln["size"] is not None, "unit_given": ln["unit"] is not None,
                 "from_image": messages[ln["message"]].get("type") == "image", "model": ch.get("confidence", "low"),
                 "repeat": ext["intent"] == "repeat_last_order", "size_from_history": size_from_history}  # fmt: skip
        r = Resolved(sku, ln["quantity"], ln["unit"], ln["action"], ln["source"], ln["message"], ln["product"],
                     ch.get("confidence", "low"), ch.get("why", ""), [c.sku for c in cands[:8]], feats)  # fmt: skip
        resolved.append(r)
        resolutions.append(
            {"line": i, "sku": sku, "confidence": r.confidence, "why": r.why, "candidates": r.candidates}
        )
    draft = build_draft(
        w, customer, ext["intent"], resolved, repeat_last=ext["intent"] == "repeat_last_order"
    )
    score_lines(draft)
    return ParseResult(draft, ext, resolutions, meter, errors)


def dumps(r: ParseResult) -> str:
    return json.dumps(r.to_dict(), ensure_ascii=False, default=str)
