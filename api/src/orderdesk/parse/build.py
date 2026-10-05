"""Turn resolved lines into a draft sales order. Deterministic: units, prices, stock, credit.

Rules (CLAUDE.md rule 1): the model said *which* SKU and *how many of what unit the customer wrote*.
Everything numeric happens here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from orderdesk.parse.world import World


@dataclass
class Resolved:
    """One line as understood: a SKU (or None), the customer's quantity and unit, and how we know."""

    sku: str | None
    qty: float | None
    unit: str | None  # carton | pack | piece, or None if the customer didn't say
    action: str = "add"  # add | remove | set
    source: str = ""
    message_index: int = 0
    product: str = ""
    confidence: str = "low"  # model's self-report: high | medium | low
    why: str = ""
    candidates: list[str] = field(default_factory=list)
    features: dict = field(default_factory=dict)


@dataclass
class DraftLine:
    sku: str | None
    qty: int
    unit: str
    qty_base: int
    unit_price_fils: int
    amount_fils: int
    source: str
    unit_from: str  # customer | history | default
    flags: list[str] = field(
        default_factory=list
    )  # unresolved, unit_guessed, out_of_stock, low_stock, from_last_order, ...
    substitutes: list[str] = field(default_factory=list)
    confidence: float = 0.0
    evidence: dict = field(default_factory=dict)


@dataclass
class Draft:
    customer: str | None
    intent: str
    lines: list[DraftLine]
    total_fils: int
    holds: list[str]  # credit_hold, unknown_customer, needs_review
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _unit_for(world: World, customer: dict | None, sku: str, unit: str | None) -> tuple[str, str]:
    if unit and world.unit_valid(sku, unit):
        return unit, "customer"
    usual = world.usual(customer["id"]).get(sku) if customer else None
    if usual and world.unit_valid(sku, usual.unit):
        return usual.unit, "history"
    s = world.skus[sku]
    return ("carton" if s["carton_size"] > 1 else "piece"), "default"


def _substitutes(world: World, sku: str, need: int) -> list[str]:
    """Same family other sizes first, then same category; only items with enough stock."""
    s = world.skus[sku]
    fam = [x["id"] for x in world.by_family[s["family"]] if x["id"] != sku]
    cat = [x["id"] for x in world.skus.values() if x["category"] == s["category"] and x["family"] != s["family"]
           and x["size_class"] == s["size_class"]]  # fmt: skip
    return [x for x in fam + cat if world.stock.get(x, 0) >= need][:3]


def build_draft(
    world: World, customer: dict | None, intent: str, resolved: list[Resolved], repeat_last: bool = False
) -> Draft:
    holds: list[str] = []
    notes: list[str] = []
    if customer is None:
        holds.append("unknown_customer")
    # 1. start from the last order if they asked to repeat it
    order: dict[str, dict] = {}
    if repeat_last and customer:
        last = world.last_order(customer["id"])
        if last:
            for ln in last["lines"]:
                order[ln["sku"]] = {"qty": ln["qty"], "unit": ln["unit"], "unit_from": "history", "source": f"last order {last['id']}",
                                    "flags": ["from_last_order"], "r": None}  # fmt: skip
            notes.append(f"Started from last order {last['id']} ({last['date']}).")
        else:
            notes.append("Customer asked to repeat the last order, but there is no order history.")
            holds.append("needs_review")
    # 2. apply each line in message order: add, set or remove
    unresolved: list[DraftLine] = []
    for r in resolved:
        if r.sku is None or r.sku not in world.skus:
            unresolved.append(DraftLine(None, int(r.qty or 0), r.unit or "piece", 0, 0, 0, r.source, "customer",
                                        ["unresolved"], evidence={"product": r.product, "why": r.why, "candidates": r.candidates}))  # fmt: skip
            continue
        if r.action == "remove":
            order.pop(r.sku, None)
            continue
        if r.qty is None or r.qty <= 0 or r.qty != int(r.qty):
            unresolved.append(DraftLine(r.sku, 0, r.unit or "piece", 0, 0, 0, r.source, "customer", ["bad_quantity"],
                                        evidence={"product": r.product, "qty": r.qty}))  # fmt: skip
            continue
        unit, unit_from = _unit_for(world, customer, r.sku, r.unit)
        if (
            r.action == "add"
            and r.sku in order
            and order[r.sku]["unit"] == unit
            and order[r.sku]["r"] is not None
        ):
            order[r.sku]["qty"] += int(r.qty)  # the same item twice: "also 2 more"
            continue
        order[r.sku] = {
            "qty": int(r.qty),
            "unit": unit,
            "unit_from": unit_from,
            "source": r.source,
            "flags": [],
            "r": r,
        }
    # 3. price, stock and flags
    lines: list[DraftLine] = []
    for sku, o in order.items():
        base = world.base_qty(sku, o["qty"], o["unit"])
        price = world.price_fils(customer, sku) if customer else world.skus[sku]["price_fils"]
        flags = list(o["flags"])
        if o["unit_from"] != "customer" and "from_last_order" not in flags:
            flags.append("unit_from_history" if o["unit_from"] == "history" else "unit_guessed")
        on_hand = world.stock.get(sku, 0)
        subs: list[str] = []
        if on_hand == 0:
            flags.append("out_of_stock")
            subs = _substitutes(world, sku, base)
        elif on_hand < base:
            flags.append("low_stock")
        r = o["r"]
        ev = {} if r is None else {"product": r.product, "why": r.why, "model_confidence": r.confidence,
                                    "candidates": r.candidates, "features": r.features, "message_index": r.message_index}  # fmt: skip
        lines.append(
            DraftLine(
                sku,
                o["qty"],
                o["unit"],
                base,
                price,
                price * base,
                o["source"],
                o["unit_from"],
                flags,
                subs,
                evidence=ev,
            )
        )
    lines += unresolved
    total = sum(ln.amount_fils for ln in lines)
    if customer and customer["balance_fils"] + total > customer["credit_limit_fils"]:
        holds.append("credit_hold")
    if unresolved or any(f in ln.flags for ln in lines for f in ("out_of_stock", "unit_guessed")):
        holds.append("needs_review")
    return Draft(customer["id"] if customer else None, intent, lines, total, sorted(set(holds)), notes)
