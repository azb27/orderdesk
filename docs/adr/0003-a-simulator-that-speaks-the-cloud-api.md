# ADR 0003: The phone simulator speaks the WhatsApp Cloud API

**Status:** accepted · **Phase:** P4

## Context
A real WhatsApp Business number needs Meta business verification, a phone number and approved templates. None of that is possible for a fictional company, and a demo that needs a reviewer's phone number is a demo nobody tries. But an "upload a message" form would skip the hard parts of the integration: signatures, retries, media downloads, message bursts.

## Decision
- The app exposes a webhook with the **Cloud API's shapes**:
  - `GET /webhooks/whatsapp` for the verify-token handshake;
  - `POST` with an `X-Hub-Signature-256` HMAC over the raw body;
  - message ids (`wamid`) as idempotency keys;
  - text and image message types.
- The **phone simulator** in the console sends the text to the server. The server builds a real Cloud API payload, signs it with the app secret, and hands it to the webhook's own verify-and-store step (`receive_webhook`), so the signature check runs on every demo message too. The parser doesn't know the difference.
- **Replies** are templates in the customer's language style (en, ar, Arabizi, Roman Hindi/Urdu), recorded as outbound messages. `channels.whatsapp.Sender` has a simulator mode and a cloud-mode stub.
- Messages from one number within 15 minutes amend the same draft, because retailers send lists in pieces.

## Consequences
- Going live is a configuration change plus finishing `Sender`'s cloud mode, not a rewrite. Unsigned or badly signed POSTs are already rejected (tested), and a repeated `wamid` is a no-op (tested).
- Media are fetched from the simulator's store, not from Meta's media endpoint. The download-and-store step is the one piece still to write for production.
- The simulator endpoint is rate-limited per IP, since it's the one public route that can cost model money.
