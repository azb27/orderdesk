"""Postgres schema. Money is integer fils; quantities are stored in the customer's unit and in base units.

Tables mirror what a distributor's desk needs: customers and products (synced from the ERP), WhatsApp
conversations and messages, draft and confirmed sales orders, a job queue, an audit log, and users.
The mock ERP keeps its own table in the `erp` schema, as a separate system would.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSONB, list[Any]: JSONB}


def _now() -> Any:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))  # order_taker | supervisor
    password_hash: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[dt.datetime] = _now()


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(30))
    area: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str] = mapped_column(String(30), unique=True)
    contact_name: Mapped[str] = mapped_column(String(100))
    tier: Mapped[str] = mapped_column(String(2))
    credit_limit_fils: Mapped[int] = mapped_column(BigInteger)
    balance_fils: Mapped[int] = mapped_column(BigInteger)
    styles: Mapped[dict[str, Any]] = mapped_column(default=dict)
    nicknames: Mapped[dict[str, Any]] = mapped_column(default=dict)
    contract_prices: Mapped[dict[str, Any]] = mapped_column(default=dict)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    family: Mapped[str] = mapped_column(String(60), index=True)
    size: Mapped[str] = mapped_column(String(20))
    name_en: Mapped[str] = mapped_column(String(200))
    name_ar: Mapped[str] = mapped_column(String(200))
    brand: Mapped[str] = mapped_column(String(60))
    category: Mapped[str] = mapped_column(String(40))
    size_label: Mapped[str] = mapped_column(String(60))
    size_class: Mapped[str] = mapped_column(String(40))
    base_unit: Mapped[str] = mapped_column(String(20))
    pack_size: Mapped[int] = mapped_column(Integer)
    carton_size: Mapped[int] = mapped_column(Integer)
    price_fils: Mapped[int] = mapped_column(BigInteger)
    barcode: Mapped[str] = mapped_column(String(13), unique=True)
    stock_on_hand: Mapped[int] = mapped_column(Integer)
    aliases: Mapped[list[Any]] = mapped_column(default=list)


class Alias(Base):
    """term -> product family. Seeded from the catalogue; grows when an order-taker teaches a new name."""

    __tablename__ = "aliases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    term: Mapped[str] = mapped_column(String(200), index=True)
    family: Mapped[str] = mapped_column(String(60))
    source: Mapped[str] = mapped_column(String(20), default="catalogue")  # catalogue | learned
    created_at: Mapped[dt.datetime] = _now()
    __table_args__ = (UniqueConstraint("term", "family"),)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone: Mapped[str] = mapped_column(String(30), index=True)
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | closed
    window_ends_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = _now()
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation", order_by="Message.received_at"
    )


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wa_id: Mapped[str] = mapped_column(String(200), unique=True)  # WhatsApp message id: the idempotency key
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    direction: Mapped[str] = mapped_column(String(3))  # in | out
    type: Mapped[str] = mapped_column(String(20))  # text | image | audio | other
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_id: Mapped[str | None] = mapped_column(ForeignKey("media.id"), nullable=True)
    received_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    raw: Mapped[dict[str, Any]] = mapped_column(default=dict)
    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Media(Base):
    """Photos sent by retailers, kept in Postgres so they survive restarts on hosts with throwaway disks."""

    __tablename__ = "media"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    content_type: Mapped[str] = mapped_column(String(40))
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[dt.datetime] = _now()


class SalesOrder(Base):
    __tablename__ = "sales_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ref: Mapped[str] = mapped_column(String(20), unique=True)
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id"), nullable=True, index=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    # history (seeded past orders) | parsing | review | confirmed | posted | post_failed | rejected
    status: Mapped[str] = mapped_column(String(20), index=True)
    intent: Mapped[str] = mapped_column(String(30), default="order")
    holds: Mapped[list[Any]] = mapped_column(default=list)
    notes: Mapped[list[Any]] = mapped_column(default=list)
    total_fils: Mapped[int] = mapped_column(BigInteger, default=0)
    parsed_by: Mapped[str | None] = mapped_column(String(60), nullable=True)  # model id, or "fallback"
    parse_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    version: Mapped[int] = mapped_column(Integer, default=1)  # optimistic concurrency for edits
    erp_ref: Mapped[str | None] = mapped_column(String(40), nullable=True)
    order_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    created_at: Mapped[dt.datetime] = _now()
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_viewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lines: Mapped[list[OrderLine]] = relationship(
        back_populates="order", order_by="OrderLine.position", cascade="all, delete-orphan"
    )
    __table_args__ = (Index("ix_orders_customer_date", "customer_id", "order_date"),)


class OrderLine(Base):
    __tablename__ = "order_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    sku: Mapped[str | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    qty: Mapped[int] = mapped_column(Integer)
    unit: Mapped[str] = mapped_column(String(10))
    qty_base: Mapped[int] = mapped_column(Integer)
    unit_price_fils: Mapped[int] = mapped_column(BigInteger)
    amount_fils: Mapped[int] = mapped_column(BigInteger)
    source_text: Mapped[str] = mapped_column(Text, default="")
    unit_from: Mapped[str] = mapped_column(String(10), default="customer")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    flags: Mapped[list[Any]] = mapped_column(default=list)
    substitutes: Mapped[list[Any]] = mapped_column(default=list)
    evidence: Mapped[dict[str, Any]] = mapped_column(default=dict)
    edited: Mapped[bool] = mapped_column(Boolean, default=False)  # changed by a person after parsing
    order: Mapped[SalesOrder] = relationship(back_populates="lines")


class Job(Base):
    """Postgres job queue: workers claim with FOR UPDATE SKIP LOCKED. No Redis, nothing lost on restart."""

    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))  # parse | post_erp | send_reply
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(10), default="queued")  # queued | running | done | dead
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    run_after: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = _now()
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (Index("ix_jobs_ready", "status", "run_after"),)


class AuditEvent(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[dt.datetime] = _now()
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)  # None = system
    action: Mapped[str] = mapped_column(String(40))
    entity: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[str] = mapped_column(String(40), index=True)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class ErpOrder(Base):
    """The mock ERP's own table (schema `erp`). Unique idempotency key: a retried post can't double-book."""

    __tablename__ = "orders"
    __table_args__ = {"schema": "erp"}  # noqa: RUF012
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    erp_ref: Mapped[str] = mapped_column(String(40), unique=True)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[dt.datetime] = _now()
