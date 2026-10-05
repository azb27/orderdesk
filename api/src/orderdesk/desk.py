"""The order desk's workflow: ingest messages, parse into drafts, edit, confirm, post to the ERP, reply.

Web routes and job handlers call these functions; nothing here knows about HTTP. Every state change writes
an audit event and publishes a live update.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import os
import threading
import time
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from orderdesk import config
from orderdesk.channels import replies
from orderdesk.channels.whatsapp import Inbound, Sender, media_exists
from orderdesk.db.models import (
    Alias,
    AuditEvent,
    Conversation,
    Customer,
    Job,
    Media,
    Message,
    OrderLine,
    Product,
    SalesOrder,
    User,
)
from orderdesk.erp.client import ErpError, post_sales_order
from orderdesk.jobs.queue import Stop, enqueue, handler
from orderdesk.parse.build import Draft, Resolved, build_draft
from orderdesk.parse.confidence import score_lines
from orderdesk.parse.fuzzy import parse_text
from orderdesk.parse.llm import Claude
from orderdesk.parse.normalize import norm
from orderdesk.parse.pipeline import parse_conversation
from orderdesk.parse.world import World, load_world_from_db
from orderdesk.web.events import publish

log = logging.getLogger("orderdesk.desk")
SUPERVISOR_THRESHOLD_FILS = int(os.environ.get("SUPERVISOR_THRESHOLD_AED", "5000")) * 100
OPEN_STATUSES = ("parsing", "review")


class DeskError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


# ---- the world, cached per process, refreshed when the desk changes it --------------------------------
_world: World | None = None
_world_at = 0.0
_world_lock = threading.Lock()


def invalidate_world() -> None:
    global _world
    with _world_lock:
        _world = None


def desk_world(s: Session, max_age_s: float = 300) -> World:
    global _world, _world_at
    with _world_lock:
        if _world is None or time.monotonic() - _world_at > max_age_s:
            _world, _world_at = load_world_from_db(s), time.monotonic()
        return _world


def audit(s: Session, actor: User | None, action: str, entity: str, entity_id: Any, before: dict | None = None,
          after: dict | None = None, note: str | None = None) -> None:  # fmt: skip
    s.add(AuditEvent(actor_id=actor.id if actor else None, action=action, entity=entity, entity_id=str(entity_id),
                     before=before, after=after, note=note))  # fmt: skip


# ---- ingest --------------------------------------------------------------------------------------------------
def ingest(s: Session, inbound: list[Inbound]) -> list[int]:
    """Store new messages (idempotent on the WhatsApp id) and schedule a parse. Returns new message ids."""
    new_ids: list[int] = []
    window = dt.timedelta(minutes=config.SESSION_WINDOW_MIN)
    for m in inbound:
        if s.scalar(select(Message.id).where(Message.wa_id == m.wa_id)) is not None:
            continue  # WhatsApp retries webhooks; a repeat is a no-op
        cust = s.scalar(select(Customer).where(Customer.phone == m.phone))
        conv = s.scalar(select(Conversation).where(Conversation.phone == m.phone, Conversation.status == "open",
                                                   Conversation.window_ends_at > m.timestamp)
                        .order_by(Conversation.id.desc()).limit(1))  # fmt: skip
        if conv is None:
            conv = Conversation(
                phone=m.phone,
                customer_id=cust.id if cust else None,
                status="open",
                window_ends_at=m.timestamp + window,
            )
            s.add(conv)
            s.flush()
        else:
            conv.window_ends_at = max(conv.window_ends_at, m.timestamp + window)
        media_id = m.media_id if m.media_id and media_exists(s, m.media_id) else None
        msg = Message(wa_id=m.wa_id, conversation_id=conv.id, direction="in", type=m.type, text=m.text or m.caption,
                      media_id=media_id, received_at=m.timestamp, raw=m.raw)  # fmt: skip
        s.add(msg)
        s.flush()
        new_ids.append(msg.id)
        delay = float(os.environ.get("PARSE_DELAY_S", "3"))  # let a burst of messages land before parsing
        enqueue(s, "parse", {"conversation_id": conv.id}, delay_s=delay)
        publish(s, "message", conversation_id=conv.id, phone=m.phone)
    return new_ids


# ---- parse -----------------------------------------------------------------------------------------------------
def llm_spend_today(s: Session) -> float:
    start = dt.datetime.now(dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return float(
        s.scalar(
            select(func.coalesce(func.sum(SalesOrder.parse_cost_usd), 0.0)).where(
                SalesOrder.created_at >= start
            )
        )
        or 0.0
    )


def model_factory() -> Any:
    """The model used for parsing. Tests replace this with a scripted fake."""
    return Claude(os.environ.get("ORDERDESK_MODEL", config.MODEL))


def _parse(s: Session, w: World, msgs: list[Message], phone: str) -> tuple[Draft, str, float, list[str]]:
    """The model pipeline when allowed and working; otherwise the fuzzy fallback, flagged for review."""
    plain = []
    for m in msgs:
        if m.type == "image" and m.media_id:
            media = s.get(Media, m.media_id)
            plain.append({"type": "image", "image_bytes": media.data if media else b"",
                          "media_type": media.content_type if media else "image/jpeg",
                          "caption": m.text or "", "ts": m.received_at.isoformat()})  # fmt: skip
        else:
            plain.append(
                {
                    "type": "text",
                    "text": m.text or ("[voice note]" if m.type == "audio" else ""),
                    "ts": m.received_at.isoformat(),
                }
            )
    budget = float(os.environ.get("LLM_DAILY_BUDGET_USD", "1.0"))
    if os.environ.get("ANTHROPIC_API_KEY") and llm_spend_today(s) < budget:
        try:
            model = globals()["model_factory"]()  # looked up at call time so tests can swap it
            r = parse_conversation(plain, phone, model, model, w=w)
            return r.draft, model.model, r.meter.cost_usd, r.errors
        except Exception as e:  # API down, rate-limited, out of credit: the desk keeps working
            log.warning("model parse failed, using fallback: %s", e)
            d = parse_text(plain, phone, w)
            d.notes.append(
                f"Read by the fallback parser (model unavailable: {type(e).__name__}). Check every line."
            )
            return d, "fallback", 0.0, [str(e)[:300]]
    d = parse_text(plain, phone, w)
    why = (
        "no API key configured"
        if not os.environ.get("ANTHROPIC_API_KEY")
        else "the demo's daily model budget is used up"
    )
    d.notes.append(f"Read by the fallback parser ({why}). Check every line.")
    return d, "fallback", 0.0, []


def _store_lines(order: SalesOrder, d: Draft) -> None:
    order.lines.clear()
    for i, ln in enumerate(d.lines):
        order.lines.append(OrderLine(position=i, sku=ln.sku, qty=ln.qty, unit=ln.unit, qty_base=ln.qty_base,
                                     unit_price_fils=ln.unit_price_fils, amount_fils=ln.amount_fils, source_text=ln.source,
                                     unit_from=ln.unit_from, confidence=ln.confidence, flags=ln.flags,
                                     substitutes=ln.substitutes, evidence=ln.evidence))  # fmt: skip
    order.total_fils, order.holds, order.notes, order.intent = d.total_fils, d.holds, d.notes, d.intent


def next_ref(s: Session) -> str:
    n = s.scalar(select(func.count(SalesOrder.id)).where(SalesOrder.status != "history")) or 0
    return f"SL-{dt.date.today():%y%m%d}-{n + 1:04d}"


@handler("parse")
def handle_parse(s: Session, payload: dict[str, Any]) -> None:
    conv = s.get(Conversation, payload["conversation_id"])
    if conv is None:
        return
    msgs = [m for m in conv.messages if m.direction == "in"]
    order = s.scalar(
        select(SalesOrder)
        .where(SalesOrder.conversation_id == conv.id)
        .order_by(SalesOrder.id.desc())
        .limit(1)
    )
    if order is not None and order.status not in OPEN_STATUSES:
        # the earlier order is already confirmed: new messages start a new draft
        last_order_at = order.confirmed_at or order.created_at
        msgs = [m for m in msgs if m.received_at > last_order_at]
        order = None
        if not msgs:
            return
    if order is not None and any(ln.edited for ln in order.lines):
        order.notes = [
            *order.notes,
            "A new message arrived after edits; the draft was not re-read. Check the conversation.",
        ]
        order.version += 1
        publish(s, "order", order_id=order.id, status=order.status)
        return
    w = desk_world(s)
    d, parsed_by, cost, errors = _parse(s, w, msgs, conv.phone)
    if d.intent == "not_order" and not d.lines:
        if order is not None:
            order.status = "rejected"
        publish(s, "conversation", conversation_id=conv.id, intent="not_order")
        audit(s, None, "classified_not_order", "conversation", conv.id)
        return
    if order is None:
        order = SalesOrder(ref=next_ref(s), customer_id=conv.customer_id, conversation_id=conv.id, status="review",
                           order_date=dt.date.today(), version=0, parse_cost_usd=0.0, holds=[], notes=[])  # fmt: skip
        s.add(order)
    _store_lines(order, d)
    order.status, order.parsed_by = "review", parsed_by
    order.parse_cost_usd = (order.parse_cost_usd or 0.0) + cost
    order.version += 1
    s.flush()
    audit(
        s,
        None,
        "parsed",
        "order",
        order.ref,
        after={"lines": len(d.lines), "holds": d.holds, "by": parsed_by, "errors": errors},
    )
    publish(s, "order", order_id=order.id, status=order.status)


# ---- edits ------------------------------------------------------------------------------------------------------
def _line_dict(ln: OrderLine) -> dict[str, Any]:
    return {"sku": ln.sku, "qty": ln.qty, "unit": ln.unit, "qty_base": ln.qty_base}


def recompute(s: Session, order: SalesOrder) -> None:
    """Rebuild prices, base quantities, flags and holds after a person edits lines (same rules as parsing)."""
    w = desk_world(s)
    cust = w.customers.get(order.customer_id) if order.customer_id else None
    resolved = [Resolved(ln.sku, ln.qty, ln.unit, "add", ln.source_text) for ln in order.lines]
    d = build_draft(w, cust, order.intent, resolved)
    by_pos = {i: ln for i, ln in enumerate(order.lines)}
    for i, dl in enumerate(d.lines):
        ln = by_pos.get(i)
        if ln is None or dl.sku != ln.sku:
            continue
        ln.qty_base, ln.unit_price_fils, ln.amount_fils = dl.qty_base, dl.unit_price_fils, dl.amount_fils
        keep = [f for f in ln.flags if f in ("from_last_order",)]
        ln.flags = keep + [f for f in dl.flags if f not in ("unit_from_history", "unit_guessed")]
        ln.substitutes = dl.substitutes
    order.total_fils = sum(ln.amount_fils for ln in order.lines)
    holds = [h for h in d.holds if h != "needs_review"]
    if any(ln.sku is None or "out_of_stock" in ln.flags for ln in order.lines):
        holds.append("needs_review")
    order.holds = sorted(set(holds))


def edit_lines(
    s: Session, order: SalesOrder, user: User, version: int, changes: list[dict[str, Any]]
) -> SalesOrder:
    """changes: [{op: update|add|delete, position?, sku?, qty?, unit?}]. Optimistic concurrency on `version`."""
    if order.status not in OPEN_STATUSES:
        raise DeskError(409, f"order is {order.status}; only drafts can be edited")
    if version != order.version:
        raise DeskError(409, "someone else changed this order; reload it")
    w = desk_world(s)
    before = [_line_dict(ln) for ln in order.lines]
    for ch in changes:
        op = ch.get("op")
        if op == "delete":
            order.lines = [ln for ln in order.lines if ln.position != ch["position"]]
            continue
        sku, qty, unit = ch.get("sku"), ch.get("qty"), ch.get("unit")
        if sku is not None and sku not in w.skus:
            raise DeskError(422, f"unknown product {sku}")
        if qty is not None and (not isinstance(qty, int) or qty <= 0 or qty > 100_000):
            raise DeskError(422, "quantity must be a positive whole number")
        if unit is not None and unit not in ("carton", "pack", "piece"):
            raise DeskError(422, "unit must be carton, pack or piece")
        if op == "add":
            if not (sku and qty and unit):
                raise DeskError(422, "a new line needs product, quantity and unit")
            pos = max((ln.position for ln in order.lines), default=-1) + 1
            order.lines.append(OrderLine(position=pos, sku=sku, qty=qty, unit=unit, qty_base=0, unit_price_fils=0, amount_fils=0,
                                         source_text="(added by order desk)", unit_from="customer", confidence=1.0, edited=True))  # fmt: skip
        elif op == "update":
            ln = next((x for x in order.lines if x.position == ch["position"]), None)
            if ln is None:
                raise DeskError(404, f"no line at position {ch['position']}")
            if sku is not None:
                ln.sku = sku
            if qty is not None:
                ln.qty = qty
            if unit is not None:
                ln.unit = unit
            ln.unit_from, ln.edited, ln.confidence = "customer", True, 1.0
        else:
            raise DeskError(422, f"unknown op {op!r}")
        if sku is not None and unit is not None and not w.unit_valid(sku, unit):
            raise DeskError(422, f"{w.skus[sku]['name_en']} isn't sold by the {unit}")
    order.lines.sort(key=lambda ln: ln.position)
    for i, ln in enumerate(order.lines):
        ln.position = i
    s.flush()
    recompute(s, order)
    order.version += 1
    if order.first_viewed_at is None:
        order.first_viewed_at = dt.datetime.now(dt.UTC)
    audit(
        s,
        user,
        "edited",
        "order",
        order.ref,
        before={"lines": before},
        after={"lines": [_line_dict(ln) for ln in order.lines]},
    )
    publish(s, "order", order_id=order.id, status=order.status)
    return order


def teach_alias(s: Session, user: User, term: str, sku: str, customer_id: str | None) -> dict[str, Any]:
    """An order-taker teaches a name: for one customer (a nickname) or for everyone (an alias for the family)."""
    term_n = norm(term)
    if not 2 <= len(term_n) <= 60:
        raise DeskError(422, "a name must be 2 to 60 characters")
    prod = s.get(Product, sku)
    if prod is None:
        raise DeskError(404, "unknown product")
    if customer_id:
        cust = s.get(Customer, customer_id)
        if cust is None:
            raise DeskError(404, "unknown customer")
        cust.nicknames = {**cust.nicknames, term_n: sku}
        what = {"customer": customer_id, "nickname": term_n, "sku": sku}
    else:
        if s.scalar(select(Alias.id).where(Alias.term == term_n, Alias.family == prod.family)) is None:
            s.add(Alias(term=term_n, family=prod.family, source="learned"))
        what = {"alias": term_n, "family": prod.family}
    audit(s, user, "taught_name", "alias", term_n, after=what)
    invalidate_world()
    return what


# ---- confirm, reject, post, reply ----------------------------------------------------------------------------
def required_role(order: SalesOrder) -> str:
    return (
        "supervisor"
        if ("credit_hold" in order.holds or order.total_fils > SUPERVISOR_THRESHOLD_FILS)
        else "order_taker"
    )


def confirm(s: Session, order: SalesOrder, user: User, version: int) -> SalesOrder:
    if order.status not in OPEN_STATUSES:
        raise DeskError(409, f"order is {order.status}")
    if version != order.version:
        raise DeskError(409, "someone else changed this order; reload it")
    if not order.lines or any(ln.sku is None or ln.qty_base <= 0 for ln in order.lines):
        raise DeskError(422, "every line needs a product and a quantity before confirming")
    if order.customer_id is None:
        raise DeskError(422, "link the conversation to a customer before confirming")
    need = required_role(order)
    if need == "supervisor" and user.role != "supervisor":
        why = (
            "credit hold"
            if "credit_hold" in order.holds
            else f"orders over AED {SUPERVISOR_THRESHOLD_FILS // 100:,}"
        )
        raise DeskError(403, f"a supervisor must confirm this order ({why})")
    order.status, order.confirmed_by, order.confirmed_at = "confirmed", user.id, dt.datetime.now(dt.UTC)
    order.version += 1
    audit(
        s, user, "confirmed", "order", order.ref, after={"total_fils": order.total_fils, "holds": order.holds}
    )
    enqueue(s, "post_erp", {"order_id": order.id})
    publish(s, "order", order_id=order.id, status=order.status)
    return order


def reject(s: Session, order: SalesOrder, user: User, reason: str) -> SalesOrder:
    if order.status not in OPEN_STATUSES:
        raise DeskError(409, f"order is {order.status}")
    order.status = "rejected"
    order.version += 1
    audit(s, user, "rejected", "order", order.ref, note=reason[:500])
    enqueue(s, "send_reply", {"order_id": order.id, "kind": "rejected"})
    publish(s, "order", order_id=order.id, status=order.status)
    return order


def erp_payload(order: SalesOrder) -> dict[str, Any]:
    return {"customer": order.customer_id, "reference": order.ref, "delivery_date": str(dt.date.today() + dt.timedelta(days=1)),
            "lines": [{"sku": ln.sku, "qty_base": ln.qty_base, "unit_price_fils": ln.unit_price_fils} for ln in order.lines],
            "total_fils": order.total_fils}  # fmt: skip


@handler("post_erp")
def handle_post_erp(s: Session, payload: dict[str, Any], client: Any = None) -> None:
    order = s.get(SalesOrder, payload["order_id"])
    if order is None or order.status not in ("confirmed", "post_failed"):
        return
    try:
        erp_ref = post_sales_order(
            erp_payload(order), key=f"orderdesk:{order.ref}", client=client or _erp_client
        )
    except ErpError as e:  # retrying won't help until someone fixes the cause; the dead hook records it
        raise Stop(str(e)) from e
    order.status, order.erp_ref = "posted", erp_ref
    cust = s.get(Customer, order.customer_id)
    if cust:
        cust.balance_fils += order.total_fils
    for ln in order.lines:
        p = s.get(Product, ln.sku)
        if p:
            p.stock_on_hand = max(0, p.stock_on_hand - ln.qty_base)
    audit(s, None, "posted_to_erp", "order", order.ref, after={"erp_ref": erp_ref})
    enqueue(s, "send_reply", {"order_id": order.id, "kind": "confirmed"})
    invalidate_world()  # history, balance and stock changed
    publish(s, "order", order_id=order.id, status=order.status)


@handler("post_erp:dead")
def handle_post_erp_dead(s: Session, payload: dict[str, Any]) -> None:
    order = s.get(SalesOrder, payload["order_id"])
    if order and order.status == "confirmed":
        order.status = "post_failed"
        if payload.get("_stopped"):
            audit(
                s,
                None,
                "erp_rejected",
                "order",
                order.ref,
                note=f"{payload.get('_error')}; fix it, then retry on the jobs page",
            )
        else:
            audit(
                s,
                None,
                "erp_post_failed",
                "order",
                order.ref,
                note="gave up after retries; see the jobs page",
            )
        publish(s, "order", order_id=order.id, status=order.status)


_erp_client: Any = None  # tests inject an in-process client here


@handler("send_reply")
def handle_send_reply(s: Session, payload: dict[str, Any]) -> None:
    order = s.get(SalesOrder, payload["order_id"])
    if order is None or order.conversation_id is None:
        return
    conv = s.get(Conversation, order.conversation_id)
    cust = s.get(Customer, order.customer_id) if order.customer_id else None
    body = replies.render(
        payload["kind"],
        cust.styles if cust else None,
        ref=order.ref,
        n=len(order.lines),
        total_fils=order.total_fils,
    )
    wa_id = Sender().send_text(conv.phone, body)
    s.add(
        Message(
            wa_id=wa_id,
            conversation_id=conv.id,
            direction="out",
            type="text",
            text=body,
            received_at=dt.datetime.now(dt.UTC),
        )
    )
    if payload["kind"] in ("confirmed", "rejected"):
        conv.status = "closed"
    publish(s, "message", conversation_id=conv.id, phone=conv.phone)


def retry_dead_job(s: Session, job_id: int, user: User) -> Job:
    job = s.get(Job, job_id)
    if job is None or job.status != "dead":
        raise DeskError(404, "no dead job with that id")
    job.status, job.attempts, job.run_after = "queued", 0, dt.datetime.now(dt.UTC)
    if job.kind == "post_erp":
        order = s.get(SalesOrder, job.payload.get("order_id"))
        if order and order.status == "post_failed":
            order.status = "confirmed"
    audit(s, user, "retried_job", "job", job.id)
    return job


def draft_dict(d: Draft) -> dict[str, Any]:
    return dataclasses.asdict(d)


__all__ = ["DeskError", "confirm", "edit_lines", "ingest", "reject", "score_lines", "teach_alias"]


def demo_cleanup(s: Session, days: int) -> dict[str, int]:
    """Public demo housekeeping: forget visitors' conversations and drafts older than `days` (history stays)."""
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
    old_orders = s.scalars(
        select(SalesOrder).where(SalesOrder.status != "history", SalesOrder.created_at < cutoff)
    ).all()
    for o in old_orders:
        s.delete(o)
    s.flush()
    old_convs = s.scalars(select(Conversation).where(Conversation.created_at < cutoff)).all()
    n_msgs = 0
    for c in old_convs:
        for m in list(c.messages):
            s.delete(m)
            n_msgs += 1
        s.delete(c)
    s.flush()
    s.execute(
        text(
            "DELETE FROM media WHERE created_at < :c AND id NOT IN (SELECT media_id FROM messages WHERE media_id IS NOT NULL)"
        ),
        {"c": cutoff},
    )
    s.execute(text("DELETE FROM jobs WHERE status = 'done' AND updated_at < :c"), {"c": cutoff})
    return {"orders": len(old_orders), "conversations": len(old_convs), "messages": n_msgs}
