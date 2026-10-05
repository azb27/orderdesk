"""The order desk end to end against real Postgres: webhook → queue → draft → edit → confirm → ERP → reply."""

from __future__ import annotations

import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from starlette.requests import Request

from orderdesk import desk
from orderdesk.channels import whatsapp
from orderdesk.db.models import Customer, ErpOrder, Job, Message, SalesOrder
from orderdesk.db.session import session_scope
from orderdesk.jobs import queue
from orderdesk.parse.build import Draft
from orderdesk.parse.llm import Scripted
from orderdesk.web.app import app
from orderdesk.web.guards import client_ip

PHONE = "+971500001004"  # C1004, an English-writing baqala in the seed data
H = {"X-Orderdesk": "1"}


@pytest.fixture
def client(db, monkeypatch):
    c = TestClient(app)
    desk._erp_client = TestClient(app, base_url="http://testserver/erp-mock/v1")
    monkeypatch.setattr(queue, "backoff", lambda attempts: 0.0)  # retries run immediately in tests
    c.post("/erp-mock/v1/faults", json={})
    yield c
    desk._erp_client = None


def send(
    c: TestClient, text: str, phone: str = PHONE, wa_id: str | None = None, ts: dt.datetime | None = None
):
    body = json.dumps(whatsapp.build_payload(phone, text=text, wa_id=wa_id, ts=ts)).encode()
    return c.post(
        "/webhooks/whatsapp",
        content=body,
        headers={"X-Hub-Signature-256": whatsapp.sign(body), "Content-Type": "application/json"},
    )


def login(c: TestClient, who: str = "maria") -> None:
    r = c.post("/api/auth/login", json={"email": f"{who}@saffronlane.example", "password": "test-password"})
    assert r.status_code == 200, r.text


def only_order(c: TestClient) -> dict:
    orders = c.get("/api/orders").json()
    assert len(orders) == 1, orders
    return c.get(f"/api/orders/{orders[0]['id']}").json()


# ---- webhook contract ------------------------------------------------------------------------------------------
def test_webhook_verification_handshake(client):
    ok = client.get(
        "/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "dev-verify-token", "hub.challenge": "42"},
    )
    assert ok.status_code == 200 and ok.text == "42"
    bad = client.get(
        "/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "42"},
    )
    assert bad.status_code == 403


def test_unsigned_or_forged_posts_are_rejected(client):
    body = json.dumps(whatsapp.build_payload(PHONE, text="2 ctn water")).encode()
    assert client.post("/webhooks/whatsapp", content=body).status_code == 401
    forged = whatsapp.sign(body, secret="someone-else")
    assert (
        client.post("/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": forged}).status_code
        == 401
    )


def test_a_redelivered_message_is_stored_once(client):
    for _ in range(3):
        assert send(client, "al wadi water 500 ml 3 ctn", wa_id="wamid.same").status_code == 200
    with session_scope() as s:
        assert s.scalar(select(func.count(Message.id))) == 1


# ---- draft → confirm → ERP → reply ----------------------------------------------------------------------------------
def test_happy_path_from_message_to_erp_and_reply(client):
    send(client, "Hi\nal wadi water 500 ml 3 ctn\nsunflower oil 1.8 l 6 pcs")
    queue.drain()
    login(client)
    o = only_order(client)
    assert o["status"] == "review" and o["parsed_by"] == "fallback" and len(o["lines"]) == 2
    assert "fallback" in o["notes"][0]
    r = client.post(f"/api/orders/{o['id']}/confirm", json={"version": o["version"]}, headers=H)
    assert r.status_code == 200, r.text
    with session_scope() as s:
        balance_before = s.get(Customer, "C1004").balance_fils
    queue.drain()
    o2 = client.get(f"/api/orders/{o['id']}").json()
    assert o2["status"] == "posted" and o2["erp_ref"].startswith("ERP-")
    with session_scope() as s:
        assert s.scalar(select(func.count(ErpOrder.id))) == 1
        assert s.get(Customer, "C1004").balance_fils == balance_before + o["total_fils"]
        reply = s.scalar(select(Message).where(Message.direction == "out"))
        assert reply is not None and o["ref"] in reply.text
    thread = client.get("/api/simulator/thread", params={"phone": PHONE}).json()
    assert thread[-1]["direction"] == "out"


def test_session_auth_and_csrf_header(client):
    assert client.get("/api/orders").status_code == 401
    assert (
        client.post(
            "/api/auth/login", json={"email": "maria@saffronlane.example", "password": "wrong"}
        ).status_code
        == 401
    )
    send(client, "al wadi water 500 ml 3 ctn")
    queue.drain()
    login(client)
    o = only_order(client)
    no_header = client.post(f"/api/orders/{o['id']}/confirm", json={"version": o["version"]})
    assert no_header.status_code == 403


def test_edits_use_optimistic_concurrency_and_recompute_totals(client):
    send(client, "al wadi water 500 ml 3 ctn")
    queue.drain()
    login(client)
    o = only_order(client)
    stale = client.patch(
        f"/api/orders/{o['id']}", json={"version": o["version"] - 1, "changes": []}, headers=H
    )
    assert stale.status_code == 409
    bad = client.patch(
        f"/api/orders/{o['id']}",
        json={"version": o["version"], "changes": [{"op": "update", "position": 0, "unit": "crate"}]},
        headers=H,
    )
    assert bad.status_code == 422
    r = client.patch(
        f"/api/orders/{o['id']}",
        json={"version": o["version"], "changes": [{"op": "update", "position": 0, "qty": 6}]},
        headers=H,
    )
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["lines"][0]["qty"] == 6 and e["lines"][0]["edited"] and e["total_fils"] == 2 * o["total_fils"]
    assert e["version"] > o["version"]
    audit = client.get("/api/audit", params={"entity": "order", "entity_id": o["ref"]}).json()
    assert [a["action"] for a in audit] == ["parsed", "edited"] and audit[1]["actor"].startswith("Maria")


def test_credit_holds_need_a_supervisor(client):
    with session_scope() as s:
        c = s.get(Customer, "C1004")
        c.balance_fils = c.credit_limit_fils  # at the limit: any order goes over
    send(client, "al wadi water 500 ml 3 ctn")
    queue.drain()
    login(client, "maria")
    o = only_order(client)
    assert "credit_hold" in o["holds"] and o["required_role"] == "supervisor"
    denied = client.post(f"/api/orders/{o['id']}/confirm", json={"version": o["version"]}, headers=H)
    assert denied.status_code == 403 and "supervisor" in denied.json()["detail"]
    client.post("/api/auth/logout")
    login(client, "omar")
    assert (
        client.post(f"/api/orders/{o['id']}/confirm", json={"version": o["version"]}, headers=H).status_code
        == 200
    )


# ---- ERP faults ----------------------------------------------------------------------------------------------------
def _confirmed_order(client) -> dict:
    send(client, "al wadi water 500 ml 3 ctn")
    queue.drain()
    login(client)
    o = only_order(client)
    assert (
        client.post(f"/api/orders/{o['id']}/confirm", json={"version": o["version"]}, headers=H).status_code
        == 200
    )
    return o


def test_erp_outage_is_retried(client):
    o = _confirmed_order(client)
    client.post("/erp-mock/v1/faults", json={"fail_next": 2})
    queue.drain()
    assert client.get(f"/api/orders/{o['id']}").json()["status"] == "posted"
    with session_scope() as s:
        job = s.scalar(select(Job).where(Job.kind == "post_erp"))
        assert job.attempts == 3 and job.status == "done"


def test_a_lost_response_does_not_double_book(client):
    o = _confirmed_order(client)
    client.post("/erp-mock/v1/faults", json={"lose_response_next": 1})
    queue.drain()
    assert client.get(f"/api/orders/{o['id']}").json()["status"] == "posted"
    with session_scope() as s:
        assert s.scalar(select(func.count(ErpOrder.id))) == 1  # booked once despite the retry


def test_dead_letter_then_supervisor_retry(client):
    o = _confirmed_order(client)
    client.post("/erp-mock/v1/faults", json={"fail_next": 10})
    queue.drain()
    assert client.get(f"/api/orders/{o['id']}").json()["status"] == "post_failed"
    dead = client.get("/api/jobs", params={"status": "dead"}).json()
    assert len(dead) == 1 and "503" in dead[0]["last_error"]
    assert client.post(f"/api/jobs/{dead[0]['id']}/retry", headers=H).status_code == 403  # order-takers can't
    client.post("/api/auth/logout")
    login(client, "omar")
    client.post("/erp-mock/v1/faults", json={})
    assert client.post(f"/api/jobs/{dead[0]['id']}/retry", headers=H).status_code == 200
    queue.drain()
    assert client.get(f"/api/orders/{o['id']}").json()["status"] == "posted"


# ---- conversations ------------------------------------------------------------------------------------------------
def test_a_follow_up_message_rereads_the_draft_until_someone_edits_it(client):
    t0 = dt.datetime.now(dt.UTC)
    send(client, "al wadi water 500 ml 3 ctn", ts=t0)
    queue.drain()
    send(client, "sunflower oil 1.8 l 6 pcs", ts=t0 + dt.timedelta(minutes=3))
    queue.drain()
    login(client)
    o = only_order(client)
    assert len(o["lines"]) == 2  # one draft for the conversation, re-read with both messages
    client.patch(
        f"/api/orders/{o['id']}",
        json={"version": o["version"], "changes": [{"op": "update", "position": 0, "qty": 4}]},
        headers=H,
    )
    send(client, "tomato paste 400 g 1 ctn", ts=t0 + dt.timedelta(minutes=5))
    queue.drain()
    o2 = client.get(f"/api/orders/{o['id']}").json()
    assert len(o2["lines"]) == 2 and o2["lines"][0]["qty"] == 4  # a person's edit is never overwritten
    assert any("new message arrived after edits" in n.lower() for n in o2["notes"])


def test_a_question_is_not_an_order(client):
    send(client, "what time is delivery today?")
    queue.drain()
    login(client)
    assert client.get("/api/orders").json() == []


def test_the_demo_phone_goes_through_the_signed_webhook(client, monkeypatch):
    checked = []
    real = whatsapp.signature_ok
    monkeypatch.setattr(whatsapp, "signature_ok", lambda body, sig: checked.append(sig) or real(body, sig))
    r = client.post("/api/simulator/send", data={"phone": PHONE, "text": "al wadi water 500 ml 2 ctn"})
    assert checked and checked[0].startswith("sha256=")  # the webhook's own signature check ran
    assert r.status_code == 200
    assert client.post("/api/simulator/send", data={"phone": "+15550000000", "text": "hi"}).status_code == 404
    queue.drain()
    login(client)
    assert only_order(client)["lines"][0]["qty"] == 2


def test_teaching_a_name_helps_the_next_order(client):
    login(client)
    send(client, "zubaida drink 330 2 ctn")
    queue.drain()
    assert client.get("/api/orders").json() == [] or all(
        ln["sku"] is None for ln in only_order(client)["lines"]
    )
    sku = client.get("/api/products", params={"q": "Mirage Orange 330"}).json()[0]["id"]
    r = client.post("/api/aliases", json={"term": "zubaida drink", "sku": sku}, headers=H)
    assert r.status_code == 200 and r.json()["family"] == "mirage_orange"
    send(client, "zubaida drink 330 2 ctn", ts=dt.datetime.now(dt.UTC) + dt.timedelta(hours=1))
    queue.drain()
    orders = client.get("/api/orders").json()
    newest = client.get(f"/api/orders/{orders[0]['id']}").json()
    assert newest["lines"][0]["product"]["family"] == "mirage_orange"


# ---- the model path ---------------------------------------------------------------------------------------------------
def test_model_parse_records_cost_and_falls_back_when_the_api_fails(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    water = client.get("/api/products", params={"q": "Al Wadi Water 500 ml"})
    login(client)
    sku = client.get("/api/products", params={"q": "Al Wadi Water 500 ml"}).json()[0]["id"]
    ext = {
        "intent": "order",
        "lines": [
            {
                "message": 0,
                "source": "mai 500 3 kartoon",
                "product": "water",
                "size": "500",
                "quantity": 3,
                "unit": "carton",
                "action": "add",
            }
        ],
    }
    monkeypatch.setattr(
        desk,
        "model_factory",
        lambda: Scripted(
            [ext, {"choices": [{"line": 0, "sku": sku, "confidence": "high", "why": "mai = water"}]}],
            model="scripted",
        ),
    )
    send(client, "mai 500 3 kartoon")
    queue.drain()
    o = only_order(client)
    assert (
        o["parsed_by"] == "scripted" and o["lines"][0]["sku"] == sku and o["lines"][0]["why"] == "mai = water"
    )
    assert water.status_code == 401  # (the product search needs a session)

    class Down:
        model = "down"

        def call(self, *a, **k):
            raise RuntimeError("529 overloaded")

    monkeypatch.setattr(desk, "model_factory", lambda: Down())
    send(client, "al wadi water 1.5 l 2 ctn", phone="+971500001011")
    queue.drain()
    newest = client.get(f"/api/orders/{client.get('/api/orders').json()[0]['id']}").json()
    assert newest["parsed_by"] == "fallback" and "model unavailable" in newest["notes"][0]


def test_a_photo_order_is_stored_in_postgres_and_reaches_the_desk(client):
    from orderdesk import config  # noqa: PLC0415

    jpg = (config.EVAL / "dev" / "images").glob("*.jpg").__next__().read_bytes()
    r = client.post(
        "/api/simulator/send",
        data={"phone": PHONE, "text": "order 👆"},
        files={"image": ("list.jpg", jpg, "image/jpeg")},
    )
    assert r.status_code == 200, r.text
    assert (
        client.post(
            "/api/simulator/send", data={"phone": PHONE}, files={"image": ("x.gif", b"GIF89a", "image/gif")}
        ).status_code
        == 415
    )
    queue.drain()
    login(client)
    o = only_order(client)
    assert o["lines"] == [] and any(
        "photo" in n.lower() for n in o["notes"]
    )  # no model in tests: a person keys it
    photo = next(m for m in o["messages"] if m["type"] == "image")
    img = client.get(f"/api/media/{photo['id']}")
    assert img.status_code == 200 and img.content == jpg and img.headers["content-type"] == "image/jpeg"


def test_demo_cleanup_forgets_old_visitor_data_but_keeps_history(client):
    send(client, "al wadi water 500 ml 3 ctn")
    queue.drain()
    with session_scope() as s:
        history = s.scalar(select(func.count(SalesOrder.id)).where(SalesOrder.status == "history"))
        for o in s.scalars(select(SalesOrder).where(SalesOrder.status != "history")):
            o.created_at = dt.datetime.now(dt.UTC) - dt.timedelta(days=5)
        from orderdesk.db.models import Conversation  # noqa: PLC0415

        for c in s.scalars(select(Conversation)):
            c.created_at = dt.datetime.now(dt.UTC) - dt.timedelta(days=5)
    with session_scope() as s:
        gone = desk.demo_cleanup(s, days=3)
    assert gone["orders"] == 1 and gone["conversations"] == 1
    with session_scope() as s:
        assert s.scalar(select(func.count(SalesOrder.id))) == history
        assert s.scalar(select(func.count(Message.id))) == 0


def test_mock_erp_refuses_callers_other_than_this_server(client):
    outsider = TestClient(app, client=("203.0.113.9", 4000))
    assert outsider.post("/erp-mock/v1/faults", json={"fail_next": 99}).status_code == 403
    r = outsider.post("/erp-mock/v1/sales-orders", json={"lines": [1]}, headers={"Idempotency-Key": "x"})
    assert r.status_code == 403


def test_rate_limit_uses_the_address_the_proxy_appended(monkeypatch):
    def req(xff: str) -> Request:
        return Request(
            {"type": "http", "headers": [(b"x-forwarded-for", xff.encode())], "client": ("10.0.0.1", 1)}
        )

    assert client_ip(req("1.1.1.1, 9.9.9.9")) == "10.0.0.1"  # not behind a trusted proxy: ignore the header
    monkeypatch.setenv("TRUST_PROXY", "1")
    assert client_ip(req("1.1.1.1, 9.9.9.9")) == "9.9.9.9"  # a forged first entry doesn't change the key


def test_an_erp_rejection_goes_straight_to_the_jobs_page_and_can_be_sent_again(client):
    o = _confirmed_order(client)
    client.post("/erp-mock/v1/faults", json={"reject_next": 1})
    queue.drain()
    assert client.get(f"/api/orders/{o['id']}").json()["status"] == "post_failed"
    dead = client.get("/api/jobs", params={"status": "dead"}).json()
    assert (
        len(dead) == 1 and dead[0]["attempts"] == 1 and "422" in dead[0]["last_error"]
    )  # no pointless retries
    trail = client.get("/api/audit", params={"entity": "order", "entity_id": o["ref"]}).json()
    assert any(e["action"] == "erp_rejected" and "blocked" in (e["note"] or "") for e in trail)
    client.post("/api/auth/logout")
    login(client, "omar")
    assert client.post(f"/api/jobs/{dead[0]['id']}/retry", headers=H).status_code == 200
    queue.drain()
    assert client.get(f"/api/orders/{o['id']}").json()["status"] == "posted"


def test_the_budget_counts_messages_that_were_not_orders(client, monkeypatch):
    def fake_parse(s, w, msgs, phone):
        return Draft(None, "not_order", [], 0, [], []), "scripted", 0.05, []

    monkeypatch.setattr(desk, "_parse", fake_parse)
    send(client, "what time is delivery today?")
    queue.drain()
    with session_scope() as s:
        assert desk.llm_spend_today(s) == pytest.approx(0.05)
