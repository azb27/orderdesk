"""WhatsApp Cloud API contract: webhook verification, signatures, payload parsing, outbound messages.

The shapes follow Meta's Cloud API webhooks (object=whatsapp_business_account, entry[].changes[].value).
In this repo the "phone" is the demo simulator, which signs its payloads with the same app secret and
posts them to the same endpoint. Going live means setting WHATSAPP_MODE=cloud plus the token and phone
number id; the cloud sender is a stub that refuses to run without them (see docs/adr/).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from orderdesk.db.models import Media


def app_secret() -> str:
    return os.environ.get("WHATSAPP_APP_SECRET", "dev-app-secret")


def verify_token() -> str:
    return os.environ.get("WHATSAPP_VERIFY_TOKEN", "dev-verify-token")


def sign(body: bytes, secret: str | None = None) -> str:
    return "sha256=" + hmac.new((secret or app_secret()).encode(), body, hashlib.sha256).hexdigest()


def signature_ok(body: bytes, header: str | None) -> bool:
    return bool(header) and hmac.compare_digest(sign(body), header or "")


@dataclass
class Inbound:
    wa_id: str
    phone: str  # E.164 with +
    type: str  # text | image | audio | other
    text: str | None
    media_id: str | None
    caption: str | None
    timestamp: dt.datetime
    profile_name: str | None
    raw: dict[str, Any]


def parse_webhook(payload: dict[str, Any]) -> list[Inbound]:
    """Every inbound message in a webhook body. Status callbacks (sent/delivered/read) are ignored."""
    out: list[Inbound] = []
    if payload.get("object") != "whatsapp_business_account":
        return out
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            names = {
                c.get("wa_id"): (c.get("profile") or {}).get("name") for c in value.get("contacts") or []
            }
            for m in value.get("messages") or []:
                kind = m.get("type")
                frm = str(m.get("from", ""))
                ts = dt.datetime.fromtimestamp(int(m.get("timestamp", "0")), tz=dt.UTC)
                text = caption = media_id = None
                if kind == "text":
                    text = (m.get("text") or {}).get("body")
                elif kind in ("image", "audio", "document"):
                    media = m.get(kind) or {}
                    media_id, caption = media.get("id"), media.get("caption")
                else:
                    kind = "other"
                out.append(Inbound(str(m.get("id")), "+" + frm.lstrip("+"), kind if kind != "document" else "other",
                                   text, media_id, caption, ts, names.get(frm), m))  # fmt: skip
    return out


def build_payload(phone: str, *, text: str | None = None, media_id: str | None = None, caption: str | None = None,
                  name: str | None = None, ts: dt.datetime | None = None, wa_id: str | None = None) -> dict[str, Any]:  # fmt: skip
    """A Cloud-API-shaped webhook body for one inbound message (used by the simulator and tests)."""
    frm = phone.lstrip("+")
    msg: dict[str, Any] = {"from": frm, "id": wa_id or f"wamid.sim.{secrets.token_hex(12)}",
                           "timestamp": str(int((ts or dt.datetime.now(dt.UTC)).timestamp()))}  # fmt: skip
    if media_id:
        msg |= {
            "type": "image",
            "image": {"id": media_id, "mime_type": "image/jpeg", **({"caption": caption} if caption else {})},
        }
    else:
        msg |= {"type": "text", "text": {"body": text or ""}}
    return {"object": "whatsapp_business_account", "entry": [{"id": "SAFFRON_LANE_WABA", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"display_phone_number": "97140000000", "phone_number_id": "SIM"},
        "contacts": [{"profile": {"name": name or "Retailer"}, "wa_id": frm}], "messages": [msg]}}]}]}  # fmt: skip


def store_media(s: Session, data: bytes, content_type: str = "image/jpeg") -> str:
    """Simulator media store: what Meta's media endpoint would hand back for a media id (kept in Postgres)."""
    media_id = secrets.token_hex(16)
    s.add(Media(id=media_id, content_type=content_type, data=data))
    s.flush()
    return media_id


def media_exists(s: Session, media_id: str) -> bool:
    return media_id.isalnum() and s.get(Media, media_id) is not None


class Sender:
    """Outbound messages. Simulator mode records them (the demo phone shows them); cloud mode is a stub."""

    def __init__(self) -> None:
        self.mode = os.environ.get("WHATSAPP_MODE", "simulator")

    def send_text(self, phone: str, body: str) -> str:
        if self.mode == "simulator":
            return f"wamid.out.{secrets.token_hex(12)}"
        token, number_id = os.environ.get("WHATSAPP_TOKEN"), os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
        if not token or not number_id:
            raise RuntimeError("WHATSAPP_MODE=cloud needs WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID")
        raise NotImplementedError(
            "Cloud sending is configuration plus one POST to /{phone_number_id}/messages; deliberately not enabled in the demo. "
            + json.dumps({"to": phone.lstrip("+"), "type": "text"})
        )
