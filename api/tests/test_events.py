"""Live updates travel Postgres NOTIFY -> the process's listener -> every subscribed stream, after commit only."""

from __future__ import annotations

import asyncio
import json

import pytest

from orderdesk.db.session import session_scope
from orderdesk.web.events import Hub, publish


@pytest.mark.asyncio
async def test_committed_events_reach_subscribers_and_rolled_back_ones_do_not(db):
    hub = Hub()
    hub.start()
    q = hub.subscribe()
    await asyncio.sleep(0.5)  # listener connects

    def commit_one() -> None:
        with session_scope() as s:
            publish(s, "order", order_id=1, status="review")

    def roll_back_one() -> None:
        try:
            with session_scope() as s:
                publish(s, "order", order_id=2, status="review")
                raise RuntimeError("abort")
        except RuntimeError:
            pass

    await asyncio.to_thread(roll_back_one)
    await asyncio.to_thread(commit_one)
    got = json.loads(await asyncio.wait_for(q.get(), timeout=5))
    assert got == {"type": "order", "order_id": 1, "status": "review"}
    assert q.empty()
    hub.unsubscribe(q)
    await hub.stop()
