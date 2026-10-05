"""What the product knows: catalogue, customers, history, stock and the alias table (data/world/).

This is the distributor's own data. Nothing here reads data/eval/truth (CLAUDE.md rule 2).
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from orderdesk import config

UNITS = ("carton", "pack", "piece")


@dataclass
class Usual:
    sku: str
    unit: str  # the unit they order it in most often
    qty: int  # their typical quantity in that unit
    times: int  # how many past orders include it


@dataclass(eq=False)  # hashable by identity, so per-world caches work
class World:
    skus: dict[str, dict]
    customers: dict[str, dict]
    by_phone: dict[str, str]
    history: dict[str, list[dict]]  # customer -> orders, oldest first
    stock: dict[str, int]
    aliases: dict[str, list[str]]  # term -> family keys
    by_family: dict[str, list[dict]] = field(default_factory=dict)
    family_name: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for s in self.skus.values():
            self.by_family.setdefault(s["family"], []).append(s)
            self.family_name.setdefault(s["family"], s["name_en"].removesuffix(" " + s["size_label"]))

    def customer_by_phone(self, phone: str) -> dict | None:
        cid = self.by_phone.get(phone)
        return self.customers.get(cid) if cid else None

    def last_order(self, customer: str) -> dict | None:
        h = self.history.get(customer)
        return h[-1] if h else None

    @cache  # noqa: B019 - World lives for the process
    def usual(self, customer: str) -> dict[str, Usual]:
        """Per SKU: how this customer usually orders it, learned from confirmed history only."""
        units: dict[str, Counter] = defaultdict(Counter)
        qtys: dict[str, list[int]] = defaultdict(list)
        for o in self.history.get(customer, []):
            for ln in o["lines"]:
                units[ln["sku"]][ln["unit"]] += 1
                qtys[ln["sku"]].append(ln["qty"])
        out = {}
        for sku, c in units.items():
            unit = c.most_common(1)[0][0]
            q = sorted(qtys[sku])
            out[sku] = Usual(sku, unit, q[len(q) // 2], sum(c.values()))
        return out

    def base_qty(self, sku: str, qty: int, unit: str) -> int:
        s = self.skus[sku]
        return qty * {"carton": s["carton_size"], "pack": s["pack_size"] or 1, "piece": 1}[unit]

    def unit_valid(self, sku: str, unit: str) -> bool:
        s = self.skus[sku]
        return (
            unit == "piece"
            or (unit == "pack" and s["pack_size"] > 0)
            or (unit == "carton" and s["carton_size"] > 1)
        )

    def price_fils(self, customer: dict, sku: str) -> int:
        if sku in customer.get("contract_prices", {}):
            return int(customer["contract_prices"][sku])
        disc = {"A": 0, "B": 200, "C": 400}[customer["tier"]]
        return round(self.skus[sku]["price_fils"] * (10_000 - disc) / 10_000)


def load_world(root: Path | None = None) -> World:
    root = root or config.WORLD
    skus = {s["id"]: s for s in json.loads((root / "catalogue.json").read_text())}
    customers = {c["id"]: c for c in json.loads((root / "customers.json").read_text())}
    hist: dict[str, list[dict]] = defaultdict(list)
    for o in json.loads((root / "history.json").read_text()):
        hist[o["customer"]].append(o)
    for v in hist.values():
        v.sort(key=lambda o: o["date"])
    return World(
        skus=skus,
        customers=customers,
        by_phone={c["phone"]: cid for cid, c in customers.items()},
        history=dict(hist),
        stock=json.loads((root / "stock.json").read_text()),
        aliases=json.loads((root / "aliases.json").read_text()),
    )


def load_world_from_db(session) -> World:
    """The same World, built from the desk's Postgres tables (the product's source of truth)."""
    from orderdesk.db.models import (  # noqa: PLC0415 - avoid a cycle
        Alias,
        Customer,
        OrderLine,
        Product,
        SalesOrder,
    )

    skus = {}
    stock = {}
    for p in session.query(Product).all():
        skus[p.id] = {
            c: getattr(p, c)
            for c in (
                "id",
                "family",
                "size",
                "name_en",
                "name_ar",
                "brand",
                "category",
                "size_label",
                "size_class",
                "base_unit",
                "pack_size",
                "carton_size",
                "price_fils",
                "barcode",
                "aliases",
            )
        }
        stock[p.id] = p.stock_on_hand
    customers = {}
    for c in session.query(Customer).all():
        customers[c.id] = {
            k: getattr(c, k)
            for k in (
                "id",
                "name",
                "type",
                "area",
                "phone",
                "contact_name",
                "tier",
                "credit_limit_fils",
                "balance_fils",
                "styles",
                "nicknames",
                "contract_prices",
            )
        }
    hist: dict[str, list[dict]] = defaultdict(list)
    rows = (
        session.query(
            SalesOrder.ref,
            SalesOrder.customer_id,
            SalesOrder.order_date,
            OrderLine.sku,
            OrderLine.qty,
            OrderLine.unit,
        )
        .join(OrderLine, OrderLine.order_id == SalesOrder.id)
        .filter(SalesOrder.status.in_(("history", "confirmed", "posted")), OrderLine.sku.isnot(None))
        .order_by(SalesOrder.order_date, SalesOrder.id, OrderLine.position)
        .all()
    )
    by_ref: dict[str, dict] = {}
    for ref, cust, date, sku, qty, unit in rows:
        if ref not in by_ref:
            by_ref[ref] = {"id": ref, "customer": cust, "date": date.isoformat() if date else "", "lines": []}
            hist[cust].append(by_ref[ref])
        by_ref[ref]["lines"].append({"sku": sku, "qty": qty, "unit": unit})
    aliases: dict[str, list[str]] = defaultdict(list)
    for a in session.query(Alias).all():
        aliases[a.term].append(a.family)
    return World(
        skus=skus,
        customers=customers,
        by_phone={c["phone"]: k for k, c in customers.items()},
        history=dict(hist),
        stock=stock,
        aliases={k: sorted(set(v)) for k, v in aliases.items()},
    )


@cache
def world() -> World:
    """The world from data/world (evals, tests and the fuzzy baseline)."""
    return load_world()
