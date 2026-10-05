"""Load the synthetic world into Postgres: products, customers, aliases, past orders, demo users.

    python -m orderdesk.seed [--reset]

Idempotent with --reset (truncates the desk's tables first). Demo passwords come from the environment
(DEMO_PASSWORD), never from the repo.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os

from argon2 import PasswordHasher
from sqlalchemy import text
from sqlalchemy.orm import Session

from orderdesk import config
from orderdesk.db.models import Alias, Customer, OrderLine, Product, SalesOrder, User
from orderdesk.db.session import session_scope

TABLES = ["order_lines", "sales_orders", "messages", "conversations", "jobs", "audit_log", "aliases", "products", "customers", "users", "erp.orders"]  # fmt: skip
DEMO_USERS = [("maria@saffronlane.example", "Maria (order desk)", "order_taker"), ("omar@saffronlane.example", "Omar (supervisor)", "supervisor")]  # fmt: skip


def reset(s: Session) -> None:
    s.execute(text("TRUNCATE " + ", ".join(TABLES) + " RESTART IDENTITY CASCADE"))


def seed(s: Session, password: str) -> dict[str, int]:
    w = config.WORLD
    cat = json.loads((w / "catalogue.json").read_text())
    stock = json.loads((w / "stock.json").read_text())
    for p in cat:
        s.add(Product(**{k: p[k] for k in ("id", "family", "size", "name_en", "name_ar", "brand", "category", "size_label", "size_class",
                                           "base_unit", "pack_size", "carton_size", "price_fils", "barcode", "aliases")},
                      stock_on_hand=stock[p["id"]]))  # fmt: skip
    custs = json.loads((w / "customers.json").read_text())
    for c in custs:
        s.add(Customer(**{k: c[k] for k in ("id", "name", "type", "area", "phone", "contact_name", "tier", "credit_limit_fils", "balance_fils",
                                            "styles", "nicknames", "contract_prices")}))  # fmt: skip
    s.flush()
    n_alias = 0
    for term, fams in json.loads((w / "aliases.json").read_text()).items():
        for f in fams:
            s.add(Alias(term=term, family=f, source="catalogue"))
            n_alias += 1
    prices = {p["id"]: p for p in cat}
    by_id = {c["id"]: c for c in custs}
    hist = json.loads((w / "history.json").read_text())
    for o in hist:
        c = by_id[o["customer"]]
        order = SalesOrder(
            ref=o["id"],
            customer_id=o["customer"],
            status="history",
            order_date=dt.date.fromisoformat(o["date"]),
        )
        total = 0
        for i, ln in enumerate(o["lines"]):
            p = prices[ln["sku"]]
            base = (
                ln["qty"] * {"carton": p["carton_size"], "pack": p["pack_size"] or 1, "piece": 1}[ln["unit"]]
            )
            disc = {"A": 0, "B": 200, "C": 400}[c["tier"]]
            unit_price = int(
                c["contract_prices"].get(ln["sku"], round(p["price_fils"] * (10_000 - disc) / 10_000))
            )
            order.lines.append(OrderLine(position=i, sku=ln["sku"], qty=ln["qty"], unit=ln["unit"], qty_base=base,
                                         unit_price_fils=unit_price, amount_fils=unit_price * base, confidence=1.0))  # fmt: skip
            total += unit_price * base
        order.total_fils = total
        s.add(order)
    ph = PasswordHasher()
    for email, name, role in DEMO_USERS:
        s.add(User(email=email, name=name, role=role, password_hash=ph.hash(password)))
    return {
        "products": len(cat),
        "customers": len(custs),
        "aliases": n_alias,
        "history_orders": len(hist),
        "users": len(DEMO_USERS),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    ap.add_argument(
        "--if-empty", action="store_true", help="seed only if there are no products yet (container start)"
    )
    a = ap.parse_args()
    password = os.environ.get("DEMO_PASSWORD", "orderdesk-demo")
    with session_scope() as s:
        if a.if_empty and s.query(Product.id).first() is not None:
            print("already seeded")
            return
        if a.reset:
            reset(s)
        print(seed(s, password))


if __name__ == "__main__":
    main()
