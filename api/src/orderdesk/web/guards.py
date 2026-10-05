"""Demo guards: per-IP rate limits for the public endpoints (the daily model budget lives in desk.py).

In-memory token buckets: right for one instance on free hosting; behind several instances they would move
to Postgres or the load balancer.
"""

from __future__ import annotations

import os
import threading
import time

from fastapi import HTTPException, Request

_buckets: dict[tuple[str, str], tuple[float, float]] = {}
_lock = threading.Lock()


def client_ip(request: Request) -> str:
    """The visitor's address. Behind a proxy (TRUST_PROXY=1) it is the last X-Forwarded-For entry, the one
    the proxy appended; earlier entries come from the client and can be forged to dodge the rate limit."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd and os.environ.get("TRUST_PROXY") == "1":
        return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(request: Request, name: str, per_minute: int) -> None:
    key = (name, client_ip(request))
    now = time.monotonic()
    with _lock:
        tokens, last = _buckets.get(key, (float(per_minute), now))
        tokens = min(float(per_minute), tokens + (now - last) * per_minute / 60)
        if tokens < 1:
            raise HTTPException(429, f"slow down: at most {per_minute} per minute")
        _buckets[key] = (tokens - 1, now)


def reset() -> None:
    with _lock:
        _buckets.clear()
