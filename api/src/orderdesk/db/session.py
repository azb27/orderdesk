"""Engine and sessions. One short-lived session per request or job; nothing holds a connection open."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from orderdesk import config


@cache
def engine(url: str | None = None) -> Engine:
    url = url or os.environ.get("DATABASE_URL", config.DATABASE_URL)
    if url.startswith("postgres://"):  # hosting providers hand out this form
        url = "postgresql+psycopg://" + url.removeprefix("postgres://")
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


def SessionLocal() -> Session:
    return sessionmaker(bind=engine(), expire_on_commit=False)()


@contextmanager
def session_scope() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency: commit on success, roll back on error."""
    with session_scope() as s:
        yield s
