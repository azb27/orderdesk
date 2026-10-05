"""The Orderdesk API and web app: WhatsApp webhook, order-desk API, live events, demo phone, static UI.

    uvicorn orderdesk.web.app:app --port 8000

A background worker thread runs the job queue in-process (one service on free hosting); the queue lives
in Postgres, so a separate worker process would work unchanged.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from rapidfuzz import fuzz, process
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from orderdesk import config, desk
from orderdesk.channels import whatsapp
from orderdesk.db.models import (
    AuditEvent,
    Conversation,
    Customer,
    Job,
    Media,
    Message,
    Product,
    SalesOrder,
    User,
)
from orderdesk.db.session import get_session, session_scope
from orderdesk.erp.mock import router as erp_router
from orderdesk.jobs.queue import Worker
from orderdesk.parse.normalize import norm
from orderdesk.web import auth
from orderdesk.web.events import hub
from orderdesk.web.guards import rate_limit

STATIC = Path(os.environ.get("ORDERDESK_STATIC", config.ROOT / "web" / "dist"))


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    if os.environ.get("DEMO_MODE") == "1":
        with session_scope() as s:
            desk.demo_cleanup(s, int(os.environ.get("DEMO_RETENTION_DAYS", "3")))
    hub.start()
    worker = None
    if os.environ.get("ORDERDESK_WORKER", "1") == "1":
        worker = Worker()
        worker.start()
    yield
    if worker:
        worker.stop()
    await hub.stop()


app = FastAPI(title="Orderdesk", version="0.1.0", lifespan=lifespan)
app.include_router(erp_router)


@app.exception_handler(desk.DeskError)
async def desk_error(_request: Request, e: desk.DeskError) -> JSONResponse:
    return JSONResponse({"detail": str(e)}, status_code=e.status)


@app.get("/healthz")
def healthz(s: Session = Depends(get_session)) -> dict[str, Any]:
    queued = s.scalar(select(func.count(Job.id)).where(Job.status == "queued")) or 0
    return {"ok": True, "queued_jobs": queued, "model": os.environ.get("ORDERDESK_MODEL", config.MODEL),
            "llm": bool(os.environ.get("ANTHROPIC_API_KEY"))}  # fmt: skip


# ---- WhatsApp webhook (Cloud API contract) --------------------------------------------------------------------
@app.get("/webhooks/whatsapp")
def wa_verify(mode: str = Query(alias="hub.mode"), token: str = Query(alias="hub.verify_token"),
              challenge: str = Query(alias="hub.challenge")) -> PlainTextResponse:  # fmt: skip
    if mode == "subscribe" and token == whatsapp.verify_token():
        return PlainTextResponse(challenge)
    raise HTTPException(403, "verification failed")


@app.post("/webhooks/whatsapp")
async def wa_inbound(request: Request) -> dict[str, Any]:
    body = await request.body()
    if not whatsapp.signature_ok(body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(401, "bad signature")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(400, "not JSON") from None
    inbound = whatsapp.parse_webhook(payload)

    def store() -> list[int]:
        with session_scope() as s:
            return desk.ingest(s, inbound)

    new = await asyncio.to_thread(store)
    return {"received": len(inbound), "new": len(new)}  # 200 fast; parsing happens in the job queue


# ---- auth -----------------------------------------------------------------------------------------------------------
class LoginIn(BaseModel):
    email: str
    password: str


def user_out(u: User) -> dict[str, Any]:
    return {"id": u.id, "name": u.name, "email": u.email, "role": u.role}


@app.post("/api/auth/login")
def login(
    body: LoginIn, response: Response, request: Request, s: Session = Depends(get_session)
) -> dict[str, Any]:
    rate_limit(request, "login", per_minute=10)
    return user_out(auth.login(s, response, body.email, body.password))


@app.post("/api/auth/logout")
def logout(response: Response) -> dict[str, bool]:
    auth.logout(response)
    return {"ok": True}


@app.get("/api/me")
def me(user: User = Depends(auth.current_user)) -> dict[str, Any]:
    return user_out(user) | {"supervisor_threshold_fils": desk.SUPERVISOR_THRESHOLD_FILS}


# ---- orders ---------------------------------------------------------------------------------------------------------
def _age_minutes(o: SalesOrder) -> int:
    return int((dt.datetime.now(dt.UTC) - o.created_at).total_seconds() // 60)


def order_summary(o: SalesOrder, cust: Customer | None) -> dict[str, Any]:
    lows = sum(1 for ln in o.lines if ln.sku is None or ln.confidence < 0.9)
    return {"id": o.id, "ref": o.ref, "status": o.status, "customer": {"id": cust.id, "name": cust.name, "area": cust.area} if cust else None,
            "lines": len(o.lines), "needs_attention": lows, "total_fils": o.total_fils, "holds": o.holds, "parsed_by": o.parsed_by,
            "created_at": o.created_at, "age_minutes": _age_minutes(o), "erp_ref": o.erp_ref, "required_role": desk.required_role(o)}  # fmt: skip


@app.get("/api/orders")
def list_orders(status: str = "open", limit: int = Query(100, le=500), s: Session = Depends(get_session),
                _u: User = Depends(auth.current_user)) -> list[dict[str, Any]]:  # fmt: skip
    q = select(SalesOrder).where(SalesOrder.status != "history")
    if status == "open":
        q = q.where(SalesOrder.status.in_(desk.OPEN_STATUSES))
    elif status != "all":
        q = q.where(SalesOrder.status == status)
    orders = s.scalars(q.order_by(SalesOrder.created_at.desc()).limit(limit)).all()
    custs = {
        c.id: c
        for c in s.scalars(
            select(Customer).where(Customer.id.in_({o.customer_id for o in orders if o.customer_id}))
        ).all()
    }
    return [order_summary(o, custs.get(o.customer_id or "")) for o in orders]


def _product_out(p: Product | None) -> dict[str, Any] | None:
    if p is None:
        return None
    return {"id": p.id, "name_en": p.name_en, "name_ar": p.name_ar, "size_label": p.size_label, "pack_size": p.pack_size,
            "carton_size": p.carton_size, "stock_on_hand": p.stock_on_hand, "family": p.family}  # fmt: skip


@app.get("/api/orders/{order_id}")
def get_order(
    order_id: int, s: Session = Depends(get_session), _u: User = Depends(auth.current_user)
) -> dict[str, Any]:
    o = s.get(SalesOrder, order_id)
    if o is None or o.status == "history":
        raise HTTPException(404, "no such order")
    if o.first_viewed_at is None and o.status in desk.OPEN_STATUSES:
        o.first_viewed_at = dt.datetime.now(dt.UTC)
    cust = s.get(Customer, o.customer_id) if o.customer_id else None
    skus = {ln.sku for ln in o.lines if ln.sku} | {x for ln in o.lines for x in (ln.substitutes or [])} | {
        x for ln in o.lines for x in (ln.evidence or {}).get("candidates", [])}  # fmt: skip
    products = {p.id: _product_out(p) for p in s.scalars(select(Product).where(Product.id.in_(skus))).all()}
    lines = [{"position": ln.position, "sku": ln.sku, "product": products.get(ln.sku or ""), "qty": ln.qty, "unit": ln.unit, "qty_base": ln.qty_base,
              "unit_price_fils": ln.unit_price_fils, "amount_fils": ln.amount_fils, "source_text": ln.source_text, "unit_from": ln.unit_from,
              "confidence": ln.confidence, "flags": ln.flags, "edited": ln.edited,
              "substitutes": [products[x] for x in ln.substitutes or [] if x in products],
              "why": (ln.evidence or {}).get("why"), "candidates": [products[x] for x in (ln.evidence or {}).get("candidates", []) if x in products]}
             for ln in o.lines]  # fmt: skip
    msgs = []
    if o.conversation_id:
        conv = s.get(Conversation, o.conversation_id)
        msgs = [{"id": m.id, "direction": m.direction, "type": m.type, "text": m.text, "at": m.received_at,
                 "has_media": bool(m.media_id)} for m in conv.messages] if conv else []  # fmt: skip
    hist = s.scalars(select(SalesOrder).where(SalesOrder.customer_id == o.customer_id, SalesOrder.status.in_(("history", "posted")), SalesOrder.id != o.id)
                     .order_by(SalesOrder.order_date.desc(), SalesOrder.id.desc()).limit(3)).all() if cust else []  # fmt: skip
    return order_summary(o, cust) | {
        "version": o.version, "intent": o.intent, "notes": o.notes, "lines": lines, "messages": msgs,
        "customer_detail": {"id": cust.id, "name": cust.name, "type": cust.type, "area": cust.area, "contact_name": cust.contact_name,
                            "credit_limit_fils": cust.credit_limit_fils, "balance_fils": cust.balance_fils, "tier": cust.tier,
                            "language": max(cust.styles, key=lambda k: cust.styles[k]) if cust.styles else "en"} if cust else None,
        "recent_orders": [{"ref": h.ref, "date": h.order_date, "lines": len(h.lines), "total_fils": h.total_fils} for h in hist],
        "confirmed_at": o.confirmed_at, "parse_cost_usd": o.parse_cost_usd,
    }  # fmt: skip


class EditIn(BaseModel):
    version: int
    changes: list[dict[str, Any]] = Field(max_length=100)


@app.patch("/api/orders/{order_id}")
def edit_order(
    order_id: int, body: EditIn, s: Session = Depends(get_session), user: User = Depends(auth.current_user)
) -> dict[str, Any]:
    o = s.get(SalesOrder, order_id)
    if o is None:
        raise HTTPException(404, "no such order")
    desk.edit_lines(s, o, user, body.version, body.changes)
    s.flush()
    return get_order(order_id, s, user)


class VersionIn(BaseModel):
    version: int


@app.post("/api/orders/{order_id}/confirm")
def confirm_order(
    order_id: int, body: VersionIn, s: Session = Depends(get_session), user: User = Depends(auth.current_user)
) -> dict[str, Any]:
    o = s.get(SalesOrder, order_id)
    if o is None:
        raise HTTPException(404, "no such order")
    desk.confirm(s, o, user, body.version)
    return {"ok": True, "status": o.status, "version": o.version}


class RejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


@app.post("/api/orders/{order_id}/reject")
def reject_order(
    order_id: int, body: RejectIn, s: Session = Depends(get_session), user: User = Depends(auth.current_user)
) -> dict[str, Any]:
    o = s.get(SalesOrder, order_id)
    if o is None:
        raise HTTPException(404, "no such order")
    desk.reject(s, o, user, body.reason)
    return {"ok": True, "status": o.status}


class AliasIn(BaseModel):
    term: str = Field(min_length=2, max_length=60)
    sku: str
    customer_id: str | None = None


@app.post("/api/aliases")
def teach(
    body: AliasIn, s: Session = Depends(get_session), user: User = Depends(auth.current_user)
) -> dict[str, Any]:
    return desk.teach_alias(s, user, body.term, body.sku, body.customer_id)


# ---- lookups --------------------------------------------------------------------------------------------------------
@app.get("/api/products")
def search_products(q: str = "", limit: int = Query(12, le=50), s: Session = Depends(get_session),
                    _u: User = Depends(auth.current_user)) -> list[dict[str, Any]]:  # fmt: skip
    prods = s.scalars(select(Product)).all()
    if not q.strip():
        return [_product_out(p) for p in prods[:limit]]  # type: ignore[misc]
    if q.isdigit() and len(q) >= 8:
        return [_product_out(p) for p in prods if p.barcode.startswith(q)][:limit]  # type: ignore[misc]
    keys = {p.id: norm(f"{p.name_en} {p.name_ar} {p.id}") for p in prods}
    hits = process.extract(norm(q), keys, scorer=fuzz.WRatio, limit=limit)
    by_id = {p.id: p for p in prods}
    return [_product_out(by_id[k]) for _, score, k in hits if score >= 50]  # type: ignore[misc]


@app.get("/api/media/{message_id}")
def media(
    message_id: int, s: Session = Depends(get_session), _u: User = Depends(auth.current_user)
) -> Response:
    m = s.get(Message, message_id)
    blob = s.get(Media, m.media_id) if m and m.media_id else None
    if blob is None:
        raise HTTPException(404, "no media")
    return Response(
        blob.data, media_type=blob.content_type, headers={"Cache-Control": "private, max-age=86400"}
    )


@app.get("/api/jobs")
def jobs(
    status: str = "dead", s: Session = Depends(get_session), _u: User = Depends(auth.current_user)
) -> list[dict[str, Any]]:
    rows = s.scalars(select(Job).where(Job.status == status).order_by(Job.id.desc()).limit(100)).all()
    return [
        {
            "id": j.id,
            "kind": j.kind,
            "payload": j.payload,
            "attempts": j.attempts,
            "last_error": j.last_error,
            "updated_at": j.updated_at,
        }
        for j in rows
    ]


@app.post("/api/jobs/{job_id}/retry")
def retry_job(
    job_id: int, s: Session = Depends(get_session), user: User = Depends(auth.supervisor)
) -> dict[str, Any]:
    j = desk.retry_dead_job(s, job_id, user)
    return {"ok": True, "status": j.status}


@app.get("/api/audit")
def audit_log(
    entity: str, entity_id: str, s: Session = Depends(get_session), _u: User = Depends(auth.current_user)
) -> list[dict[str, Any]]:
    rows = s.scalars(
        select(AuditEvent)
        .where(AuditEvent.entity == entity, AuditEvent.entity_id == entity_id)
        .order_by(AuditEvent.id)
    ).all()
    users = {u.id: u.name for u in s.scalars(select(User)).all()}
    return [
        {
            "at": e.at,
            "actor": users.get(e.actor_id or 0, "system"),
            "action": e.action,
            "before": e.before,
            "after": e.after,
            "note": e.note,
        }
        for e in rows
    ]


@app.get("/api/stats")
def stats(s: Session = Depends(get_session), _u: User = Depends(auth.current_user)) -> dict[str, Any]:
    start = dt.datetime.now(dt.UTC) - dt.timedelta(hours=24)
    by_status = dict(s.execute(select(SalesOrder.status, func.count()).where(SalesOrder.status != "history", SalesOrder.created_at >= start)
                               .group_by(SalesOrder.status)).all())  # fmt: skip
    dead = s.scalar(select(func.count(Job.id)).where(Job.status == "dead")) or 0
    secs = s.scalar(select(func.avg(func.extract("epoch", SalesOrder.confirmed_at - SalesOrder.first_viewed_at)))
                    .where(SalesOrder.confirmed_at >= start, SalesOrder.first_viewed_at.isnot(None)))  # fmt: skip
    return {"last_24h": by_status, "dead_jobs": dead, "avg_seconds_to_confirm": float(secs) if secs else None,
            "llm_spend_today_usd": round(desk.llm_spend_today(s), 4), "llm_budget_usd": float(os.environ.get("LLM_DAILY_BUDGET_USD", "1.0"))}  # fmt: skip


@app.get("/api/events")
async def events(request: Request, _u: User = Depends(auth.current_user)) -> StreamingResponse:
    try:
        q = hub.subscribe()
    except RuntimeError:
        raise HTTPException(503, "too many live connections") from None

    async def stream() -> AsyncIterator[str]:
        try:
            yield "retry: 3000\n\n"
            while not await request.is_disconnected():
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {payload}\n\n"
                except TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            hub.unsubscribe(q)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---- the demo phone (simulates a retailer's WhatsApp) ---------------------------------------------------------------
@app.get("/api/simulator/customers")
def sim_customers(s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    custs = s.scalars(select(Customer).order_by(Customer.id).limit(40)).all()
    return [{"id": c.id, "name": c.name, "phone": c.phone, "contact_name": c.contact_name, "type": c.type,
             "language": max(c.styles, key=lambda k: c.styles[k]) if c.styles else "en"} for c in custs]  # fmt: skip


async def _post_signed(payload: dict[str, Any]) -> None:
    """Deliver like Meta would: sign the body and call the real webhook handler."""
    body = json.dumps(payload).encode()

    def store() -> None:
        assert whatsapp.signature_ok(body, whatsapp.sign(body))
        with session_scope() as s:
            desk.ingest(s, whatsapp.parse_webhook(json.loads(body)))

    await asyncio.to_thread(store)


def _sim_customer(s: Session, phone: str) -> Customer:
    c = s.scalar(select(Customer).where(Customer.phone == phone))
    if c is None:
        raise HTTPException(404, "the demo phone can only send as a demo customer")
    return c


@app.post("/api/simulator/send")
async def sim_send(
    request: Request, phone: str = Form(...), text: str = Form(""), image: UploadFile | None = File(None)
) -> dict[str, Any]:
    rate_limit(request, "simulator", per_minute=int(os.environ.get("SIM_PER_MINUTE", "8")))
    if len(text) > 1500:
        raise HTTPException(413, "message too long for the demo (1,500 characters)")
    with session_scope() as s:
        c = _sim_customer(s, phone)
        name = c.contact_name
    media_id = None
    if image is not None:
        data = await image.read()
        if len(data) > 3_000_000:
            raise HTTPException(413, "image too large for the demo (3 MB)")
        if not data.startswith((b"\xff\xd8", b"\x89PNG")):
            raise HTTPException(415, "send a JPEG or PNG")
        with session_scope() as s:
            media_id = whatsapp.store_media(
                s, data, "image/png" if data.startswith(b"\x89PNG") else "image/jpeg"
            )
    elif not text.strip():
        raise HTTPException(422, "type a message or attach a photo")
    payload = whatsapp.build_payload(phone, text=text if media_id is None else None, media_id=media_id,
                                     caption=text or None, name=name)  # fmt: skip
    await _post_signed(payload)
    return {"ok": True}


@app.get("/api/simulator/thread")
def sim_thread(phone: str, s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    _sim_customer(s, phone)
    rows = s.execute(select(Message).join(Conversation, Conversation.id == Message.conversation_id).where(Conversation.phone == phone)
                     .order_by(Message.received_at.desc()).limit(30)).scalars().all()  # fmt: skip
    return [
        {"id": m.id, "direction": m.direction, "type": m.type, "text": m.text, "at": m.received_at}
        for m in reversed(rows)
    ]


# ---- the React app (built into web/dist) --------------------------------------------------------------------------------
if STATIC.exists():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith(("api/", "webhooks/", "erp-mock/")):
            raise HTTPException(404)
        f = STATIC / path
        return FileResponse(f if path and f.is_file() else STATIC / "index.html")
