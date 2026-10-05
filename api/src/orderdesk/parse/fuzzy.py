"""A parser with no model: split lines, read numbers and unit words, fuzzy-match product names.

Two jobs: the eval's baseline (what you get without an LLM), and the product's fallback when the model API
is down, so orders still reach the desk, every line flagged for review.
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz, process

from orderdesk.parse.build import Draft, Resolved, build_draft
from orderdesk.parse.normalize import norm
from orderdesk.parse.retrieve import _index, _size_numbers
from orderdesk.parse.vocab import NUMBER_WORDS, WORD_TO_UNIT
from orderdesk.parse.world import World, world

REPEAT = re.compile(r"\b(same|repeat|last order|last week|nafs|pichla|pichle)\b|نفس")
REMOVE = re.compile(r"^(no|without|bdoon|بدون)\s+(.+)$|^(.+?)\s+nahi chahiye$")
SIZE_NUM = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|l|ltr|litre|liter|g|gm|gram|kg|kilo|s)\b")
SPLIT = re.compile(r"\n|,|\s\+\s|\band\b|\baur\b")


def _segments(text: str) -> list[str]:
    return [s.strip(" -•.") for s in SPLIT.split(text) if s and s.strip(" -•.")]


def _qty_unit(seg: str) -> tuple[int | None, str | None, str]:
    """(quantity, unit, product text left over). Size numbers ("330 ml", "5 kg") are not quantities."""
    t = norm(seg)
    t = re.sub(r"^\d+[.)]\s+", "", t)  # list numbering
    sizes = [m.group(0) for m in SIZE_NUM.finditer(t)]
    rest = SIZE_NUM.sub(" ", t)
    unit = None
    for w in rest.split():
        if w in WORD_TO_UNIT:
            unit = WORD_TO_UNIT[w]
    m = re.search(r"(\d+)\s*(?:x\b)|x\s*(\d+)\b|(\d+)\s*(?=[a-z؀-ۿ]*\s*$)", rest)
    nums = re.findall(r"\b\d+\b", rest)
    qty = None
    if m:
        qty = int(next(g for g in m.groups() if g))
    elif nums:
        qty = int(nums[-1] if len(nums) > 1 else nums[0])
    else:
        for w in rest.split():
            if w in NUMBER_WORDS:
                qty = NUMBER_WORDS[w]
                break
    words = [
        w
        for w in rest.split()
        if w not in WORD_TO_UNIT and w not in NUMBER_WORDS and not w.isdigit() and w != "x"
    ]
    return qty, unit, " ".join(words + sizes)


def _match(w: World, customer: dict | None, text: str) -> tuple[str | None, float]:
    keys, fams = _index(w)
    best = process.extractOne(norm(text), keys, scorer=fuzz.token_set_ratio)
    if not best or best[1] < 70:
        return None, 0.0
    hist = w.usual(customer["id"]) if customer else {}
    options = fams[best[2]]
    in_hist = [f for f in options if any(w.skus[s]["family"] == f for s in hist)]
    fam = (in_hist or options)[0]
    sizes = w.by_family[fam]
    want = _size_numbers(text)
    by_size = [s for s in sizes if want & _size_numbers(s["size_label"])]
    usual = [s for s in sizes if s["id"] in hist]
    pick = (by_size or usual or sizes)[0]
    return pick["id"], float(best[1])


def parse_text(messages: list[dict], phone: str, w: World | None = None) -> Draft:
    w = w or world()
    customer = w.customer_by_phone(phone)
    resolved: list[Resolved] = []
    repeat = False
    any_text = False
    for i, m in enumerate(messages):
        if m.get("type") != "text":
            continue  # no OCR in the fallback: photos go straight to a human
        any_text = True
        text = m.get("text", "")
        if REPEAT.search(norm(text)):
            repeat = True
            text = (
                re.split(r"\b(but|bs|lekin)\b|بس", text, maxsplit=1)[-1]
                if re.search(r"\b(but|bs|lekin)\b|بس", text)
                else ""
            )
        for seg in _segments(text):
            rm = REMOVE.match(norm(seg))
            if rm and repeat:
                sku, _ = _match(w, customer, next(g for g in rm.groups() if g))
                if sku:
                    resolved.append(Resolved(sku, 1, None, "remove", seg, i))
                continue
            seg = re.sub(r"^(add|also|w zeed|zeed|aur|وزيد)\s+", "", seg, flags=re.I)
            qty, unit, prod = _qty_unit(seg)
            if not prod or qty is None:
                continue
            sku, score = _match(w, customer, prod)
            if sku is None:
                continue
            resolved.append(Resolved(sku, qty, unit, "add", seg, i, prod, "low", f"fuzzy {score:.0f}",
                                     features={"fuzzy": score, "model": "low"}))  # fmt: skip
    intent = "repeat_last_order" if repeat else ("order" if resolved or not any_text else "not_order")
    draft = build_draft(w, customer, intent, resolved, repeat_last=repeat)
    for ln in draft.lines:
        ln.confidence = 0.0
        if "needs_review" not in draft.holds:
            draft.holds.append("needs_review")
    if not any_text:
        draft.notes.append("Photo order: the fallback parser can't read images; key it from the photo.")
    return draft
