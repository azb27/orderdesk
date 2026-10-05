"""Render known orders as WhatsApp conversations, with ground truth.

A conversation is one or two messages from one retailer. The truth is the order the distributor should
book: SKU and quantity in base units per line, plus how each line was written (style, whether the name
was seen or held out, whether size and unit were stated). The generator only omits a size or unit, or
uses an ambiguous name, when the customer's own history makes the meaning recoverable; otherwise the
truth would be unknowable and the eval unfair.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field

import numpy as np

from orderdesk.world.catalogue import Sku
from orderdesk.world.customers import Customer
from orderdesk.world.lexicon import (
    ARABIC_INDIC,
    CLOSINGS,
    GENERIC,
    GREETINGS,
    NUMBER_WORDS,
    OPENERS,
    UNIT_WORDS,
    size_terms,
    split_terms,
    street_terms,
)


@dataclass
class TruthLine:
    sku: str
    qty: int  # in the unit below
    unit: str  # carton | pack | piece
    qty_base: int
    style: str
    term: str
    term_seen: bool
    via: str  # term | nickname | history
    size_given: bool
    unit_given: bool


@dataclass
class Conversation:
    id: str
    customer: str
    phone: str
    split: str
    kind: str  # order | usual | amend | not_order
    channel: str  # text | image
    messages: list[dict] = field(default_factory=list)  # {id, ts, type: text|image, text?, image?, caption?}


@dataclass
class Truth:
    id: str
    customer: str
    kind: str
    lines: list[TruthLine]
    lead_style: str


def base_qty(sku: Sku, qty: int, unit: str) -> int:
    return qty * {"carton": sku.carton_size, "pack": sku.pack_size or 1, "piece": 1}[unit]


class Renderer:
    def __init__(self, skus: list[Sku], families: dict, history: list[dict], rng: np.random.Generator):
        self.skus = {s.id: s for s in skus}
        self.by_family: dict[str, list[Sku]] = {}
        for s in skus:
            self.by_family.setdefault(s.family, []).append(s)
        self.families = families
        self.rng = rng
        self.terms = {k: street_terms(f) for k, f in families.items()}
        self.heldout = {k: set(v) for k, v in split_terms()[1].items()}
        self.term_families: dict[str, set[str]] = {}
        for fam, by_style in self.terms.items():
            for ts in by_style.values():
                for t in ts:
                    self.term_families.setdefault(t, set()).add(fam)
        for t, fams in GENERIC.items():  # generic words cover a whole group of families
            self.term_families.setdefault(t, set()).update(fams)
        self.last_order: dict[str, dict] = {}
        for o in history:
            self.last_order[o["customer"]] = o  # history is sorted by customer, date

    def size_words(self, sku: Sku, style: str) -> list[str]:
        """Size words that pick out this size within its family (words shared with a sibling size are dropped)."""
        mine = size_terms(sku.size_label, sku.size_class, style)
        others: set[str] = set()
        for s in self.by_family[sku.family]:
            if s.id != sku.id:
                others |= set(size_terms(s.size_label, s.size_class, style))
        uniq = [w for w in mine if w not in others]
        return uniq or [sku.size_label]

    # ---- one line --------------------------------------------------------------------------------
    def _choice(self, xs):
        return xs[int(self.rng.integers(len(xs)))]

    def _typo(self, s: str) -> str:
        if len(s) < 5 or not s.isascii() or self.rng.random() > 0.12:
            return s
        i = int(self.rng.integers(1, len(s) - 1))
        op = self.rng.integers(3)
        if op == 0:
            return s[:i] + s[i + 1 :]  # drop
        if op == 1:
            return s[:i] + s[i] + s[i:]  # double
        return s[: i - 1] + s[i] + s[i - 1] + s[i + 1 :]  # swap

    def _qty_text(self, qty: int, style: str) -> str:
        words = NUMBER_WORDS[style].get(qty)
        if words and self.rng.random() < 0.18:
            return self._choice(words)
        txt = str(qty)
        if style == "ar" and self.rng.random() < 0.5:
            txt = txt.translate(ARABIC_INDIC)
        return txt

    def _unit_word(self, sku: Sku, unit: str, style: str) -> str:
        key = "bag" if (unit == "piece" and sku.base_unit == "bag") else unit
        return self._choice(UNIT_WORDS[key][style])

    def line(
        self, c: Customer, sku: Sku, qty: int, unit: str, style: str, from_basket: bool
    ) -> tuple[str, TruthLine]:
        fam_skus = self.by_family[sku.family]
        basket_fams = {self.skus[b.sku].family for b in c.usual}
        basket_same_fam = [b for b in c.usual if self.skus[b.sku].family == sku.family]
        # product words
        nick = next((n for n, s in c.nicknames.items() if s == sku.id), None)
        via, term = "term", ""
        if nick and self.rng.random() < 0.5:
            via, term = "nickname", nick
        else:
            opts = []
            for t in self.terms[sku.family][style]:
                fams = self.term_families[t]
                if len(fams) == 1 or (from_basket and len(fams & basket_fams) == 1):
                    opts.append(t)
            if not opts:  # fall back to the official name, which is unique
                opts = [
                    self.families[sku.family].name_ar
                    if style == "ar"
                    else self.families[sku.family].name_en.lower()
                ]
            term = self._choice(opts)
        term_seen = via == "nickname" or term not in self.heldout.get(sku.family, set())
        # size words
        size_given = True
        if via == "nickname":
            size_given = False
        elif len(fam_skus) == 1 and self.rng.random() < 0.6:
            size_given = False
        elif from_basket and len(basket_same_fam) == 1 and self.rng.random() < 0.35:
            size_given = False
        size_txt = self._choice(self.size_words(sku, style)) if size_given else ""
        # unit words
        usual = next((b for b in basket_same_fam if b.sku == sku.id), None)
        unit_given = not (usual and usual.usual_unit == unit and self.rng.random() < 0.3)
        unit_txt = self._unit_word(sku, unit, style) if unit_given else ""
        if not size_given and not unit_given and not usual:
            unit_given, unit_txt = True, self._unit_word(sku, unit, style)
        q = self._qty_text(qty, style)
        prod = self._typo(term)
        prod_full = f"{prod} {size_txt}".strip()
        qu = f"{q} {unit_txt}".strip()
        if style == "en":
            fmts = [
                f"{qu} {prod_full}",
                f"{prod_full} - {qu}",
                f"{prod_full} {q}{unit_txt}",
                f"{prod_full} {qu}",
            ]
            if q.isdigit():
                fmts.append(f"{prod_full} x{q} {unit_txt}".strip())
        elif style == "ar":
            fmts = [f"{prod_full} {qu}", f"{qu} {prod_full}", f"{unit_txt} {prod_full} {q}".strip()]
        elif style == "arabizi":
            fmts = [f"{qu} {prod_full}", f"{prod_full} {qu}", f"{prod_full} {q} {unit_txt}".strip()]
        else:
            fmts = [
                f"{prod_full} {qu}",
                f"{qu} {prod_full}",
                f"{prod_full} ki {qu}",
                f"{prod_full} {qu} bhejo",
            ]
        text = " ".join(self._choice(fmts).split())
        tl = TruthLine(
            sku.id, qty, unit, base_qty(sku, qty, unit), style, term, term_seen, via, size_given, unit_given
        )
        return text, tl

    # ---- whole messages ------------------------------------------------------------------------------
    def _style(self, c: Customer) -> str:
        ks = list(c.styles)
        p = np.array([c.styles[k] for k in ks])
        return str(self.rng.choice(ks, p=p / p.sum()))

    def _pick_lines(self, c: Customer, n: int) -> list[tuple[Sku, int, str, bool]]:
        out: list[tuple[Sku, int, str, bool]] = []
        used: set[str] = set()
        cats = {self.skus[b.sku].category for b in c.usual}
        others = [s for s in self.skus.values() if s.category in cats]
        while len(out) < n:
            if self.rng.random() < 0.8:
                b = c.usual[int(self.rng.integers(len(c.usual)))]
                sku, unit, from_basket = self.skus[b.sku], b.usual_unit, True
                qty = max(1, round(b.usual_qty * float(self.rng.choice([0.5, 1, 1, 1, 1.5, 2]))))
                if self.rng.random() < 0.15:  # sometimes a different unit than usual
                    unit = str(
                        self.rng.choice(
                            [u for u in ("carton", "pack", "piece") if u != "pack" or sku.pack_size]
                        )
                    )
            else:
                sku, from_basket = others[int(self.rng.integers(len(others)))], False
                unit = "carton" if sku.carton_size > 1 and self.rng.random() < 0.6 else "piece"
                qty = (
                    int(self.rng.choice([1, 2, 3, 5]))
                    if unit == "carton"
                    else int(self.rng.choice([2, 4, 6, 10, 12]))
                )
            if sku.id in used or (unit == "carton" and sku.carton_size == 1):
                continue
            used.add(sku.id)
            out.append((sku, qty, unit, from_basket))
        return out

    def _wrap(self, style: str, lines: list[str]) -> str:
        sep = str(self.rng.choice(["\n", "\n", "\n", ", ", "\n", " + "]))
        if sep == "\n" and self.rng.random() < 0.2:
            lines = [f"{i}. {x}" if self.rng.random() < 0.6 else f"- {x}" for i, x in enumerate(lines, 1)]
        body = sep.join(lines)
        head = " ".join(x for x in (self._choice(GREETINGS[style]), self._choice(OPENERS[style])) if x)
        tail = self._choice(CLOSINGS[style])
        parts = [p for p in (head, body, tail) if p]
        return "\n".join(parts) if sep == "\n" else " ".join(parts)

    def order_lines(self, c: Customer, n: int, lead: str) -> tuple[list[str], list[TruthLine]]:
        texts, truth = [], []
        for sku, qty, unit, fb in self._pick_lines(c, n):
            style = lead if self.rng.random() > 0.15 else self._style(c)  # some code-switching
            t, tl = self.line(c, sku, qty, unit, style, fb)
            texts.append(t)
            truth.append(tl)
        return texts, truth

    def conversation(
        self, cid: str, c: Customer, split: str, ts: dt.datetime, kind: str, image: bool
    ) -> tuple[Conversation, Truth]:
        lead = self._style(c)
        conv = Conversation(cid, c.id, c.phone, split, kind, "image" if image else "text")
        lo, hi = {"baqala": (3, 12), "cafeteria": (2, 7), "restaurant": (2, 6), "mini_market": (5, 14)}[
            c.type
        ]
        n = int(self.rng.integers(lo, hi + 1))
        mid = f"wamid.{cid}"
        if kind == "not_order":
            q = {
                "en": [
                    "What time is delivery today?",
                    "Pls send statement for September",
                    "Price of oil 1.5 pls",
                    "Driver not came yet",
                ],
                "ar": ["متى التوصيل اليوم؟", "ارسل كشف الحساب لو سمحت", "كم سعر الزيت؟"],
                "arabizi": ["el delivery mata?", "abi kashf 7isab", "kam si3r el zait"],
                "roman": ["bhai gaadi kab aayegi?", "invoice bhejo bhai", "tel ka rate kya hai?"],
            }[lead]
            conv.messages.append(
                {"id": f"{mid}.1", "ts": ts.isoformat(), "type": "text", "text": self._choice(q)}
            )
            return conv, Truth(cid, c.id, kind, [], lead)
        if kind == "usual":
            last = self.last_order[c.id]
            truth = []
            for ln in last["lines"]:
                sku = self.skus[ln["sku"]]
                truth.append(
                    TruthLine(
                        sku.id,
                        ln["qty"],
                        ln["unit"],
                        base_qty(sku, ln["qty"], ln["unit"]),
                        lead,
                        "(last order)",
                        True,
                        "history",
                        False,
                        False,
                    )
                )
            mods: list[str] = []
            if len(truth) > 1 and self.rng.random() < 0.6:  # drop one line
                drop = truth.pop(int(self.rng.integers(len(truth))))
                fam = self.families[self.skus[drop.sku].family]
                name = self._choice(
                    [t for t in self.terms[fam.key][lead] if len(self.term_families[t]) == 1]
                    or [fam.name_en.lower()]
                )
                mods.append(
                    {
                        "en": f"no {name}",
                        "ar": f"بدون {name}",
                        "arabizi": f"bdoon {name}",
                        "roman": f"{name} nahi chahiye",
                    }[lead]
                )
            if self.rng.random() < 0.6:  # add one line
                t, tl = self.order_lines(c, 1, lead)
                if tl[0].sku not in {x.sku for x in truth}:
                    truth.append(tl[0])
                    mods.append(
                        {
                            "en": f"add {t[0]}",
                            "ar": f"وزيد {t[0]}",
                            "arabizi": f"w zeed {t[0]}",
                            "roman": f"aur {t[0]}",
                        }[lead]
                    )
            head = {"en": ["same as last order", "repeat last order", "same like last week"], "ar": ["نفس الطلب الماضي", "نفس طلبية الأسبوع الماضي"],
                    "arabizi": ["nafs el order el ma9i", "nafs el talab"], "roman": ["pichla order same", "last week wala order same bhejo"]}[lead]  # fmt: skip
            but = {"en": " but ", "ar": " بس ", "arabizi": " bs ", "roman": " lekin "}[lead]
            text = self._choice(head) + (but + ", ".join(mods) if mods else "")
            conv.messages.append({"id": f"{mid}.1", "ts": ts.isoformat(), "type": "text", "text": text})
            return conv, Truth(cid, c.id, kind, truth, lead)
        texts, truth = self.order_lines(c, n, lead)
        if kind == "amend" and len(truth) >= 3:
            k = 1 if self.rng.random() < 0.6 else 2
            first_t, first_tl = texts[:-k], truth[:-k]
            later_t = texts[-k:]
            conv.messages.append(
                {"id": f"{mid}.1", "ts": ts.isoformat(), "type": "text", "text": self._wrap(lead, first_t)}
            )
            pre = {"en": ["also", "sorry forgot", "add pls", "+"], "ar": ["وزيد", "نسيت", "أضف"], "arabizi": ["w zeed", "nseet", "zeed"], "roman": ["aur ye bhi", "bhool gaya", "ye bhi add karo"]}[lead]  # fmt: skip
            ts2 = ts + dt.timedelta(minutes=int(self.rng.integers(2, 12)))
            conv.messages.append(
                {
                    "id": f"{mid}.2",
                    "ts": ts2.isoformat(),
                    "type": "text",
                    "text": f"{self._choice(pre)} " + ", ".join(later_t),
                }
            )
            return conv, Truth(cid, c.id, kind, first_tl + truth[-k:], lead)
        if image:
            conv.messages.append({"id": f"{mid}.1", "ts": ts.isoformat(), "type": "image", "lines": texts, "style": lead,
                                  "caption": self._choice(["", "order 👆", "pls send", self._choice(GREETINGS[lead])])})  # fmt: skip
        else:
            conv.messages.append(
                {"id": f"{mid}.1", "ts": ts.isoformat(), "type": "text", "text": self._wrap(lead, texts)}
            )
        return conv, Truth(cid, c.id, "order", truth, lead)


def generate(renderer: Renderer, customers: list[Customer], split: str, n: int, start: dt.datetime,
             p_image: float = 0.15) -> tuple[list[Conversation], list[Truth]]:  # fmt: skip
    rng = renderer.rng
    convs, truths = [], []
    for i in range(n):
        c = customers[int(rng.integers(len(customers)))]
        kind = str(rng.choice(["order", "usual", "amend", "not_order"], p=[0.70, 0.12, 0.12, 0.06]))
        image = kind == "order" and rng.random() < p_image / 0.70
        ts = start + dt.timedelta(minutes=int(rng.integers(0, 60 * 24 * 5)))
        ts = ts.replace(hour=int(rng.choice([7, 8, 9, 10, 10, 11, 11, 12, 13, 13, 14, 15])))
        conv, truth = renderer.conversation(f"{split}-{i + 1:03d}", c, split, ts, kind, image)
        convs.append(conv)
        truths.append(truth)
    return convs, truths


def to_json(x) -> dict:
    return asdict(x)
