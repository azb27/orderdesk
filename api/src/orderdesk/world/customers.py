"""Saffron Lane's customers: retailers with a language mix, price tier, credit, usual basket and 12 weeks of history.

Everything here is visible to the product (it is what the distributor's ERP would hold). Phone numbers are
fictional: all are in +971 50 000 xxxx, a range chosen to look obviously fake.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field

import numpy as np

from orderdesk.world.catalogue import Sku

AREAS = ["Al Quoz", "Deira", "Karama", "Satwa", "Bur Dubai", "Al Barsha", "Jumeirah", "International City",
         "Al Nahda (Sharjah)", "Rolla (Sharjah)", "Al Qusais", "Muhaisnah", "JLT", "Discovery Gardens"]  # fmt: skip
TYPES = {  # share, basket size range, language profile weights (en, ar, arabizi, roman)
    "baqala": (0.55, (8, 22), [(0.45, (0.35, 0.05, 0.05, 0.55)), (0.35, (0.25, 0.30, 0.40, 0.05)), (0.20, (0.60, 0.10, 0.10, 0.20))]),
    "cafeteria": (0.25, (5, 14), [(0.6, (0.50, 0.0, 0.05, 0.45)), (0.4, (0.40, 0.25, 0.30, 0.05))]),
    "restaurant": (0.12, (5, 12), [(0.5, (0.70, 0.10, 0.10, 0.10)), (0.5, (0.30, 0.30, 0.35, 0.05))]),
    "mini_market": (0.08, (15, 30), [(1.0, (0.55, 0.15, 0.15, 0.15))]),
}  # fmt: skip
# category preferences by customer type (weights for sampling the usual basket)
CATEGORY_WEIGHT = {
    "baqala": {"soft_drinks": 3, "water": 3, "juice": 2, "dairy": 3, "eggs": 1, "bakery": 2, "snacks": 3, "staples": 2, "pulses": 1, "oil_tea_coffee": 2, "canned": 2, "household": 2, "energy": 1},
    "cafeteria": {"soft_drinks": 3, "water": 3, "juice": 2, "dairy": 3, "eggs": 2, "bakery": 3, "snacks": 1, "staples": 1, "pulses": 1, "oil_tea_coffee": 3, "canned": 2, "household": 1, "energy": 1},
    "restaurant": {"soft_drinks": 2, "water": 3, "juice": 1, "dairy": 2, "eggs": 2, "bakery": 2, "snacks": 0.2, "staples": 3, "pulses": 3, "oil_tea_coffee": 3, "canned": 3, "household": 2, "energy": 0.2},
    "mini_market": {"soft_drinks": 3, "water": 3, "juice": 3, "dairy": 3, "eggs": 1, "bakery": 2, "snacks": 3, "staples": 3, "pulses": 2, "oil_tea_coffee": 3, "canned": 3, "household": 3, "energy": 2},
}  # fmt: skip
TIERS = {"A": 0, "B": 200, "C": 400}  # discount in basis points
NAME_PARTS = {
    "baqala": (["Al Noor", "Al Madina", "Hassan", "Al Baraka", "Green Valley", "Kerala", "Al Shams", "Star", "Al Amal", "New Day", "Fresh Point", "Al Wafa", "Moonlight", "Al Rahma", "Lulu Star", "City Corner"], ["Grocery", "Baqala", "Foodstuff", "Supermarket", "Groceries"]),
    "cafeteria": (["Al Reef", "Kerala Hut", "Tasty", "Al Fanar", "Chai Point", "Karak House", "Golden", "Royal", "Al Qasr", "Spice Box", "Shawarma Station"], ["Cafeteria", "Cafe", "Cafeteria & Juice", "Snacks"]),
    "restaurant": (["Al Diwan", "Biryani", "Lahore", "Damascus", "Saffron", "Zaatar", "Mandi", "Malabar", "Al Yaman", "Bombay"], ["Restaurant", "Kitchen", "House", "Grill"]),
    "mini_market": (["Family", "Al Ain", "Prime", "Daily Fresh", "Corner", "Smart Choice"], ["Mini Market", "Supermarket", "Hypermarket"]),
}  # fmt: skip


@dataclass
class BasketItem:
    sku: str
    usual_qty: int  # in the customer's usual unit
    usual_unit: str  # carton | pack | piece
    weekly_prob: float


@dataclass
class Customer:
    id: str
    name: str
    type: str
    area: str
    phone: str
    contact_name: str
    styles: dict[str, float]  # language style -> share of their lines
    tier: str
    credit_limit_fils: int
    balance_fils: int
    usual: list[BasketItem] = field(default_factory=list)
    contract_prices: dict[str, int] = field(default_factory=dict)  # sku -> fils per base unit
    nicknames: dict[str, str] = field(default_factory=dict)  # their private name -> sku id

    def to_dict(self) -> dict:
        return asdict(self)


CONTACTS = {"roman": ["Shafeeq", "Rashid", "Imran", "Anwar", "Salim", "Faisal", "Nazar", "Jaleel", "Asif", "Tariq"],
            "ar": ["Abu Ahmed", "Khalid", "Mohammed", "Yousef", "Omar", "Abu Saeed", "Hamad", "Majid"],
            "en": ["Joseph", "Ravi", "Suresh", "Ali", "Ahmed", "Ramesh", "John", "Babu"]}  # fmt: skip


def _usual_unit(sku: Sku, ctype: str, rng: np.random.Generator) -> str:
    big = ctype in ("baqala", "mini_market")
    if sku.carton_size == 1:
        return "piece"
    if big:
        return str(rng.choice(["carton", "carton", "carton", "pack" if sku.pack_size else "piece"]))
    return str(rng.choice(["carton", "piece", "piece"] + (["pack"] if sku.pack_size else [])))


def build_customers(skus: list[Sku], rng: np.random.Generator, n: int = 180) -> list[Customer]:
    by_cat: dict[str, list[Sku]] = {}
    for s in skus:
        by_cat.setdefault(s.category, []).append(s)
    types = list(TYPES)
    shares = np.array([TYPES[t][0] for t in types])
    out: list[Customer] = []
    used_names: set[str] = set()
    for i in range(n):
        ctype = str(rng.choice(types, p=shares / shares.sum()))
        _, (lo, hi), profiles = TYPES[ctype]
        pw = np.array([p for p, _ in profiles])
        prof = profiles[int(rng.choice(len(profiles), p=pw / pw.sum()))][1]
        styles = {s: float(w) for s, w in zip(("en", "ar", "arabizi", "roman"), prof, strict=True) if w > 0}
        first, second = NAME_PARTS[ctype]
        name = f"{rng.choice(first)} {rng.choice(second)}"
        while name in used_names:
            name = f"{rng.choice(first)} {rng.choice(second)} {int(rng.integers(2, 9))}"
        used_names.add(name)
        lead = max(styles, key=lambda k: styles[k])
        contact = str(
            rng.choice(CONTACTS["roman" if lead == "roman" else "ar" if lead in ("ar", "arabizi") else "en"])
        )
        # usual basket: categories by type preference, one size per family mostly (so "milk" is unambiguous for them)
        w = CATEGORY_WEIGHT[ctype]
        k = int(rng.integers(lo, hi + 1))
        cats = list(by_cat)
        cw = np.array([w.get(c, 1) for c in cats], dtype=float)
        basket: list[BasketItem] = []
        fam_seen: set[str] = set()
        tries = 0
        while len(basket) < k and tries < 500:
            tries += 1
            cat = str(rng.choice(cats, p=cw / cw.sum()))
            sku = by_cat[cat][int(rng.integers(len(by_cat[cat])))]
            if sku.family in fam_seen and rng.random() < 0.85:  # mostly one size per family
                continue
            if any(b.sku == sku.id for b in basket):
                continue
            fam_seen.add(sku.family)
            unit = _usual_unit(sku, ctype, rng)
            qty = (
                int(rng.choice([1, 1, 2, 2, 3, 4, 5, 6, 10]))
                if unit == "carton"
                else int(rng.choice([2, 3, 5, 6, 10, 12, 20, 24]))
            )
            if unit == "pack":
                qty = int(rng.choice([1, 2, 3, 4, 5]))
            basket.append(BasketItem(sku.id, qty, unit, float(rng.uniform(0.3, 0.95))))
        tier = str(rng.choice(list(TIERS), p=[0.5, 0.35, 0.15]))
        limit = int(rng.choice([5_000, 10_000, 15_000, 25_000, 40_000])) * 100
        balance = int(
            limit
            * float(
                rng.choice(
                    [rng.uniform(0.1, 0.6), rng.uniform(0.6, 0.95), rng.uniform(0.95, 1.1)],
                    p=[0.7, 0.22, 0.08],
                )
            )
        )
        c = Customer(
            id=f"C{1001 + i}", name=name, type=ctype, area=str(rng.choice(AREAS)),
            phone=f"+97150000{1001 + i:04d}", contact_name=contact, styles=styles, tier=tier,
            credit_limit_fils=limit, balance_fils=balance, usual=basket,
        )  # fmt: skip
        if rng.random() < 0.08:  # a few contract prices
            for b in basket[:3]:
                base = next(s for s in skus if s.id == b.sku).price_fils
                c.contract_prices[b.sku] = round(base * 0.92)
        out.append(c)
    return out


NICKNAME_TEMPLATES = {
    "soft_drinks": ["red can", "the black one", "small can", "fizzy"], "water": ["small water", "big water", "blue bottle"],
    "dairy": ["the green milk", "blue laban", "red cap"], "snacks": ["red chips", "the blue packet", "kids chips"],
    "staples": ["the big bag", "our rice", "white bag"], "oil_tea_coffee": ["yellow oil", "the red tea", "big tin"],
}  # fmt: skip


def add_nicknames(customers: list[Customer], skus: dict[str, Sku], rng: np.random.Generator) -> None:
    """A third of customers have one or two private names for products, learned by the order desk over time."""
    for c in customers:
        if rng.random() > 0.33:
            continue
        for b in rng.permutation(c.usual)[:2]:
            sku = skus[b.sku]
            opts = NICKNAME_TEMPLATES.get(sku.category)
            if not opts:
                continue
            nick = str(rng.choice(opts))
            if nick not in c.nicknames:
                c.nicknames[nick] = sku.id


def build_history(customers: list[Customer], rng: np.random.Generator, weeks: int = 12,
                  end: dt.date = dt.date(2026, 10, 1)) -> list[dict]:  # fmt: skip
    """Past confirmed orders: 1-3 a week per customer, drawn from their usual basket with noise."""
    orders = []
    n = 500_000
    for c in customers:
        per_week = 1 if c.type == "restaurant" else int(rng.choice([1, 2, 2, 3]))
        for w in range(weeks):
            for k in range(per_week):
                day = end - dt.timedelta(
                    days=7 * (weeks - w) - int(k * 7 / per_week) - int(rng.integers(0, 2))
                )
                lines = []
                for b in c.usual:
                    if rng.random() < b.weekly_prob:
                        q = max(1, round(b.usual_qty * float(rng.choice([0.5, 1, 1, 1, 1, 1.5, 2]))))
                        lines.append({"sku": b.sku, "qty": q, "unit": b.usual_unit})
                if not lines:
                    b = c.usual[0]
                    lines.append({"sku": b.sku, "qty": b.usual_qty, "unit": b.usual_unit})
                n += 1
                orders.append({"id": f"SO-{n}", "customer": c.id, "date": day.isoformat(), "lines": lines})
    orders.sort(key=lambda o: (o["customer"], o["date"]))
    return orders


def build_stock(skus: list[Sku], rng: np.random.Generator) -> dict[str, int]:
    """On-hand base units per SKU; about 4% are out of stock (exercises substitution)."""
    out = {}
    for s in skus:
        out[s.id] = 0 if rng.random() < 0.04 else int(s.carton_size * rng.integers(5, 200))
    return out
