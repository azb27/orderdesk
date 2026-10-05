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


@cache
def world() -> World:
    return load_world()
