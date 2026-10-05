# Process map: the order desk before and after

*Fictional engagement. Times and volumes marked **(brief)** come from the discovery memo and are not measurements.*

## Today

```mermaid
flowchart LR
    R[Retailer<br/>WhatsApp text or photo] --> P[Shared WhatsApp phone]
    P --> OT[Order-taker reads it,<br/>works out the products<br/>from memory]
    OT -->|unclear| Q[Asks the retailer<br/>on WhatsApp] --> P
    OT --> K[Keys each line<br/>into the ERP]
    K --> C{Credit checked?}
    C -->|often not| W[16:00 pick list<br/>to warehouse]
    C -->|over limit| CC[Credit controller<br/>by phone] --> W
    W --> D[Next-day delivery]
    D -->|wrong pack, variant,<br/>missed line| X[Dispute,<br/>credit note, re-delivery]
```

| Step | Who | Time (brief) | What goes wrong |
|---|---|---|---|
| Read the message | Order-taker | — | Slang, Arabizi, photos; "same as last week" means looking up last week |
| Work out SKUs | Order-taker | most of the 6–10 min per order | Pack size and variant guessed from memory |
| Clarify | Order-taker ↔ retailer | minutes to hours | Order waits; peak backlog grows |
| Key into ERP | Order-taker | line by line | Typos; carton vs piece |
| Credit check | Order-taker, then credit controller | often skipped | Orders shipped to customers over their limit |
| Cut-off | Warehouse | 16:00 | Late orders roll to the day after |

## With Orderdesk (v1: a person confirms every order)

```mermaid
flowchart LR
    R[Retailer<br/>unchanged: WhatsApp] -->|Cloud API webhook,<br/>signed| I[Orderdesk inbox]
    I --> J[Parse job<br/>extract → retrieve → resolve → build]
    J --> D[Draft order<br/>prices, stock, credit,<br/>evidence per line]
    D --> OT[Order-taker checks<br/>tinted lines, confirms]
    OT -->|edits a name once| A[Learned alias<br/>used for every customer]
    OT --> H{Hold?}
    H -->|credit or > AED 5,000| S[Supervisor releases]
    H -->|no| E[ERP post<br/>idempotency key, retries]
    S --> E
    E --> M[Template reply in the<br/>retailer's language]
    E --> W[16:00 pick list]
```

| Step | Who | What changes |
|---|---|---|
| Read and match | Orderdesk | The draft is ready in seconds (Sonnet p50 7.4 s on the eval). Every line shows the words it came from and why that product won |
| Check | Order-taker | Reads the tinted lines (low confidence, unusual quantity, out of stock, unit guessed); the rest are there to glance at. Keyboard: j/k between orders, arrows between lines, e to edit, Enter to confirm |
| Fix | Order-taker | One click on another candidate the parser considered, or search by English name, Arabic name or barcode. "Teach this name" turns a correction into an alias |
| Credit | System | Holds are computed, not remembered. Only a supervisor can confirm a held order |
| Post | System | One post per order, idempotent. ERP outages retry with backoff, then show up on the Jobs page |
| Reply | System | A confirmation template in the retailer's language style. No free-form AI text to customers |

## Who touches what

| Role | Today | With Orderdesk |
|---|---|---|
| Retailer | WhatsApp | WhatsApp, unchanged. Gets a confirmation in their language |
| Order-taker | Reads, guesses, keys | Checks, fixes, confirms; teaches names |
| Supervisor / credit controller | Phone calls about limits | Confirms held and high-value orders in the same console |
| IT | ERP admin | Watches the Jobs page and the health check; no new servers to babysit beyond one container and Postgres |
| Salesmen | Relay orders by phone | No change in v1 |

## What stays manual on purpose

- **Confirming every order.** This changes only by the rollout plan's gates ([rollout-plan.md](rollout-plan.md)).
- **Substitutions.** Out-of-stock lines suggest substitutes; a person picks one.
- **Anything that isn't an order.** Complaints, invoice questions and delivery problems are flagged "not an order" and left to a person.
