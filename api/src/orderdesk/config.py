"""Single source of truth for paths, seeds, money and model settings."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("ORDERDESK_ROOT", Path(__file__).resolve().parents[3]))  # set in the container
DATA = Path(os.environ.get("ORDERDESK_DATA", ROOT / "data"))
WORLD = DATA / "world"  # catalogue, customers, prices, stock, history (what the product can see)
EVAL = DATA / "eval"  # eval messages and images (what the parser sees)
TRUTH = EVAL / "truth"  # ground truth: tests and evals only (CLAUDE.md rule 2)
RUNS = ROOT / "runs"

SEED = 2026
TZ = "Asia/Dubai"
CURRENCY = "AED"
FILS_PER_AED = 100

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://orderdesk@127.0.0.1:5433/orderdesk")
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://orderdesk@127.0.0.1:5433/orderdesk_test"
)

MODEL = os.environ.get("ORDERDESK_MODEL", "claude-sonnet-5")
CHEAP_MODEL = os.environ.get("ORDERDESK_CHEAP_MODEL", "claude-haiku-4-5-20251001")

SESSION_WINDOW_MIN = 15  # messages from one retailer within this window amend the same draft
CUTOFF_LOCAL = "16:00"  # next-day delivery cut-off, Dubai time
