# Data handling note

*For Saffron Lane's operations manager and whoever advises them on data protection (fictional). It describes what the system as built does with data, and what has to be decided before real messages flow. It is not legal advice. The legal points are questions for the client's counsel, not conclusions.*

## What data the system holds

| Data | Personal? | Where it comes from | Where it lives |
|---|---|---|---|
| Retailer phone numbers, contact names | Yes | WhatsApp messages, ERP customer master | Postgres `customers`, `conversations`, `messages` |
| Message text and photos of order lists | Can be: names, handwriting, sometimes other people in a photo | WhatsApp | Postgres `messages`, `media` |
| Orders, prices, credit limits, balances | Commercial; tied to a business, sometimes a sole trader | ERP and the desk | Postgres `sales_orders`, `order_lines`, `customers` |
| Staff accounts and actions | Yes (staff) | Created by the admin | Postgres `users`, `audit_log` |
| Model requests | Message text and photos, the business name, its usual products | Sent to the Anthropic API per order | Not stored by Orderdesk except an optional response cache (below) |

All state is in one Postgres database. The application keeps nothing on local disk except the LLM response cache. In production that cache is off, or kept on an encrypted volume with the same retention as messages.

## What goes to the model provider, and what doesn't

**Sent per order:**

- the message text, or the photo, with its timestamp;
- the customer's business name, type and area;
- for each line, a short list of candidate products, with the customer's usual quantities and their own nicknames for products.

**Never sent:** phone numbers, contact names, credit limits, balances, prices, staff identities. The model doesn't need any of these. Prices and credit are computed in code after the model step (ADR 0001).

Anthropic's commercial terms say API data is not used for training without permission. Zero data retention is available by arrangement. Before go-live, confirm the current [API data retention terms](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention) and decide whether to request zero retention.

## Retention

| Data | Proposed retention | Mechanism |
|---|---|---|
| Messages and photos | 90 days after the order is posted, then deleted. The order keeps its lines and the source words for each line | A scheduled job, like the demo's start-up cleanup (`desk.demo_cleanup`) but on the production schedule |
| Orders and audit log | As long as the ERP keeps sales records (financial records) | Not deleted by Orderdesk |
| Learned aliases | Indefinitely. They are product vocabulary, not personal data | Reviewable and deletable by a supervisor |
| Staff accounts | Disabled when someone leaves. Their audit entries stay | Admin |

The public demo keeps visitors' orders and messages for 3 days (`DEMO_RETENTION_DAYS`). Its customers are fictional.

## Access

- Two roles: **order-taker** (read and confirm orders within credit) and **supervisor** (also credit holds, high-value orders, retrying failed jobs). Production would map these to the client's directory with single sign-on.
- Every change to an order is in the audit log with who, when, before and after. The log is append-only from the application.
- Photos are served only to signed-in staff (`/api/media/...` requires a session).
- Webhook calls are verified with the Meta app secret. Unsigned requests are rejected.

## Questions for Saffron Lane's counsel before go-live

1. The UAE's federal data protection law (Federal Decree-Law No. 45 of 2021) covers personal data processed in the UAE. Does processing retailer contacts and order messages for order fulfilment need any step beyond what the existing customer relationship already covers?
2. The model provider processes message content outside the UAE. Is a cross-border transfer mechanism or a contract clause needed, and does a zero-retention arrangement change the answer?
3. Are retailers told, for example in the WhatsApp Business profile or on invoices, that orders are processed with automated help and checked by staff?
4. What is the retention period for order messages under the client's existing records policy? It should set the 90-day default above.

## What would change this note

Voice notes (speech-to-text adds another processor), free-form AI replies to customers (out of scope by design), or any use of message data to train or fine-tune models (not planned, and it would need its own approval).
