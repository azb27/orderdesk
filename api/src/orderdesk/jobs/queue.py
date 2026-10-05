"""A Postgres job queue. Claim with FOR UPDATE SKIP LOCKED, retry with backoff, park in 'dead' after max.

Every state change commits, so a crash mid-job leaves the job 'running' with locked_at set; a stale lock
(older than LOCK_TIMEOUT) is reclaimed by the next worker. Nothing lives only in memory.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
import traceback
from collections.abc import Callable
from typing import Any

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from orderdesk.db.models import Job
from orderdesk.db.session import session_scope

log = logging.getLogger("orderdesk.jobs")
LOCK_TIMEOUT = dt.timedelta(minutes=5)
HANDLERS: dict[str, Callable[[Session, dict[str, Any]], None]] = {}


class Retry(Exception):
    """Raise from a handler to retry later (counts as an attempt)."""


class Stop(Exception):
    """A failure that retrying won't fix (the ERP rejected the order): dead-letter now, so a person can fix the
    cause and retry it from the jobs page."""


def handler(kind: str):
    def deco(fn):
        HANDLERS[kind] = fn
        return fn

    return deco


def enqueue(s: Session, kind: str, payload: dict[str, Any], delay_s: float = 0, max_attempts: int = 5) -> Job:
    job = Job(kind=kind, payload=payload, max_attempts=max_attempts,
              run_after=dt.datetime.now(dt.UTC) + dt.timedelta(seconds=delay_s))  # fmt: skip
    s.add(job)
    s.flush()
    s.execute(text("SELECT pg_notify('orderdesk_jobs', :k)"), {"k": kind})
    return job


def claim(s: Session) -> Job | None:
    now = dt.datetime.now(dt.UTC)
    q = (
        select(Job)
        .where(or_(Job.status == "queued", (Job.status == "running") & (Job.locked_at < now - LOCK_TIMEOUT)))
        .where(Job.run_after <= now)
        .order_by(Job.run_after, Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = s.execute(q).scalar_one_or_none()
    if job:
        job.status, job.locked_at, job.attempts = "running", now, job.attempts + 1
    return job


def backoff(attempts: int) -> float:
    return min(300.0, 2.0**attempts)


def run_one() -> bool:
    """Claim and run one job. Returns False if there was nothing to do."""
    with session_scope() as s:
        job = claim(s)
        if job is None:
            return False
        job_id, kind, payload = job.id, job.kind, dict(job.payload)
    try:
        with session_scope() as s:
            HANDLERS[kind](s, payload)
            j = s.get(Job, job_id)
            assert j is not None
            j.status, j.locked_at, j.last_error = "done", None, None
    except Exception as e:  # any failure: retry with backoff, or dead-letter
        err = f"{type(e).__name__}: {e}"[:2000]
        if not isinstance(e, Retry):
            log.warning("job %s (%s) failed: %s\n%s", job_id, kind, err, traceback.format_exc(limit=3))
        with session_scope() as s:
            j = s.get(Job, job_id)
            assert j is not None
            j.last_error, j.locked_at = err, None
            if j.attempts >= j.max_attempts or isinstance(e, Stop):
                j.status = "dead"
                on_dead = HANDLERS.get(f"{kind}:dead")
                if on_dead:
                    on_dead(s, {**payload, "_error": str(e), "_stopped": isinstance(e, Stop)})
            else:
                j.status = "queued"
                j.run_after = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=backoff(j.attempts))
    return True


def drain(max_jobs: int = 1000) -> int:
    """Run jobs until the queue is empty or not yet due (tests and scripts)."""
    n = 0
    while n < max_jobs and run_one():
        n += 1
    return n


class Worker(threading.Thread):
    """Background worker thread started by the web app. Polls every `interval` seconds when idle."""

    def __init__(self, interval: float = 0.5) -> None:
        super().__init__(daemon=True, name="orderdesk-worker")
        self.interval = interval
        self.stopping = threading.Event()

    def run(self) -> None:
        while not self.stopping.is_set():
            try:
                busy = run_one()
            except Exception:  # never let the worker die (e.g. the database restarting)
                log.exception("worker loop error")
                busy = False
            if not busy:
                time.sleep(self.interval)

    def stop(self) -> None:
        self.stopping.set()
