"""Post confirmed orders to the ERP. Same idempotency key on every retry, so retries can't double-book."""

from __future__ import annotations

import os
from typing import Any

import httpx

from orderdesk.jobs.queue import Retry


class ErpError(Exception):
    """A permanent rejection (4xx): retrying won't help; a person must look."""


def base_url() -> str:
    return os.environ.get("ERP_URL", "http://127.0.0.1:8000/erp-mock/v1")


def post_sales_order(
    payload: dict[str, Any], key: str, client: httpx.Client | None = None, timeout: float = 10.0
) -> str:
    c = client or httpx.Client(base_url=base_url(), timeout=timeout)
    try:
        r = c.post("/sales-orders", json=payload, headers={"Idempotency-Key": key})
    except httpx.TransportError as e:  # timeouts, refused connections: try again later
        raise Retry(f"ERP unreachable: {e}") from e
    finally:
        if client is None:
            c.close()
    if r.status_code >= 500:
        raise Retry(f"ERP {r.status_code}")
    if r.status_code >= 400:
        raise ErpError(f"ERP rejected the order: {r.status_code} {r.text[:300]}")
    return str(r.json()["erp_ref"])
