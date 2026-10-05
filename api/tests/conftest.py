"""Backend tests run against a real Postgres (the orderdesk_test database), never mocks of it."""

from __future__ import annotations

import json
import os

os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://orderdesk@127.0.0.1:5433/orderdesk_test"),
)
os.environ["ORDERDESK_WORKER"] = "0"  # tests drain the queue themselves
os.environ["PARSE_DELAY_S"] = "0"
os.environ.pop("ANTHROPIC_API_KEY", None)  # no real model calls from tests
os.environ["DEMO_PASSWORD"] = "test-password"

import pytest
from sqlalchemy import text

from orderdesk.db.session import engine, session_scope

_seeded = False


def _world_json(name: str):
    from orderdesk import config  # noqa: PLC0415

    return json.loads((config.WORLD / f"{name}.json").read_text())


def _ensure_schema_and_seed() -> None:
    global _seeded
    if _seeded:
        return
    from alembic.config import Config  # noqa: PLC0415

    from alembic import command  # noqa: PLC0415
    from orderdesk import config  # noqa: PLC0415
    from orderdesk.seed import reset, seed  # noqa: PLC0415

    cfg = Config(str(config.ROOT / "api" / "alembic.ini"))
    cfg.set_main_option("script_location", str(config.ROOT / "api" / "alembic"))
    command.upgrade(cfg, "head")
    with session_scope() as s:
        reset(s)
        seed(s, "test-password")
    _seeded = True


@pytest.fixture
def db():
    """A seeded database with the desk's working tables emptied before each test (history kept)."""
    _ensure_schema_and_seed()
    with engine().begin() as c:
        c.execute(
            text(
                "DELETE FROM order_lines WHERE order_id IN (SELECT id FROM sales_orders WHERE status <> 'history')"
            )
        )
        c.execute(text("DELETE FROM sales_orders WHERE status <> 'history'"))
        c.execute(
            text(
                "TRUNCATE messages, media, conversations, jobs, audit_log, erp.orders RESTART IDENTITY CASCADE"
            )
        )
        c.execute(text("DELETE FROM aliases WHERE source = 'learned'"))
        for cust in _world_json("customers"):
            c.execute(text("UPDATE customers SET balance_fils = :b, nicknames = CAST(:n AS jsonb) WHERE id = :i"),
                      {"b": cust["balance_fils"], "n": json.dumps(cust["nicknames"]), "i": cust["id"]})  # fmt: skip
        for sku, n in _world_json("stock").items():
            c.execute(text("UPDATE products SET stock_on_hand = :n WHERE id = :i"), {"n": n, "i": sku})
    from orderdesk import desk  # noqa: PLC0415
    from orderdesk.web import guards  # noqa: PLC0415

    desk.invalidate_world()
    guards.reset()
    yield
