"""Live updates: Postgres NOTIFY -> one LISTEN connection per process -> every open SSE stream.

Works across processes (the worker thread or another instance notifies; every web process hears it).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from typing import Any

import psycopg
from sqlalchemy import text
from sqlalchemy.orm import Session

from orderdesk import config

log = logging.getLogger("orderdesk.events")
CHANNEL = "orderdesk_events"
MAX_CLIENTS = 50


def publish(s: Session, kind: str, **data: Any) -> None:
    """Queue an event; Postgres delivers it when the transaction commits (never for a rolled-back change)."""
    s.execute(
        text("SELECT pg_notify(:c, :p)"), {"c": CHANNEL, "p": json.dumps({"type": kind, **data}, default=str)}
    )


class Hub:
    def __init__(self) -> None:
        self.clients: set[asyncio.Queue[str]] = set()
        self.task: asyncio.Task | None = None

    def subscribe(self) -> asyncio.Queue[str]:
        if len(self.clients) >= MAX_CLIENTS:
            raise RuntimeError("too many live connections")
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
        self.clients.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[str]) -> None:
        self.clients.discard(q)

    def broadcast(self, payload: str) -> None:
        for q in list(self.clients):
            with contextlib.suppress(asyncio.QueueFull):  # a stuck client misses events, not the others
                q.put_nowait(payload)

    async def listen(self) -> None:
        url = os.environ.get("DATABASE_URL", config.DATABASE_URL).replace(
            "postgresql+psycopg://", "postgresql://"
        )
        url = url.replace("postgres://", "postgresql://", 1) if url.startswith("postgres://") else url
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(url, autocommit=True) as conn:
                    await conn.execute(f"LISTEN {CHANNEL}")
                    async for n in conn.notifies():
                        self.broadcast(n.payload)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # reconnect after a database restart
                log.warning("event listener reconnecting: %s", e)
                await asyncio.sleep(2)

    def start(self) -> None:
        if self.task is None:
            self.task = asyncio.get_running_loop().create_task(self.listen())

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
            self.task = None


hub = Hub()
