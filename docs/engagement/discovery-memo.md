# Discovery memo: Saffron Lane order desk

*Week 1 of a fictional engagement. Saffron Lane Foodstuff Trading LLC is invented. Figures marked **(brief)** are what the customer told us in discovery, written to be plausible for a Dubai FMCG distributor. They are inputs to the plan, not results. Results live in `docs/results/` and come from runs.*

## Who we talked to
| Person | Role | What they care about |
|---|---|---|
| Operations manager | Owns the order desk and the 16:00 cut-off | Orders keyed on time, fewer delivery disputes |
| Order-desk lead + 4 order-takers | Read WhatsApp, key orders into the ERP | Fewer "what does he mean?" messages, not being blamed for the retailer's typo |
| Credit controller | Approves customers over their limit | No orders shipped to customers on hold |
| IT (one person, part-time) | ERP admin, WhatsApp Business accounts | Nothing that needs a server he has to babysit |
| Two salesmen | Own customer relationships | Customers keep ordering the way they already do |

## How it works today
1. Retailers send orders to one of two WhatsApp Business numbers, any time from 06:00. Most arrive 09:00–14:00. **(brief)** ~650 messages a day at peak, ~180 active customers.
2. An order-taker reads the message, works out the products (often by memory of what that shop usually buys), and keys the order line by line into the ERP. **(brief)** 6–10 minutes per order; long lists and photos take longest.
3. Unclear lines get a WhatsApp reply ("which Pepsi?"), and the order waits.
4. Orders over the customer's credit limit are supposed to be held for the credit controller. In practice the order-taker often doesn't check.
5. At 16:00 the ERP order list goes to the warehouse for picking and next-day delivery.

## What goes wrong (brief)
- **Wrong pack size:** "2 Pepsi" keyed as 2 pieces instead of 2 cartons, or the reverse. The most common dispute.
- **Wrong variant:** diet vs regular, 330 ml can vs 500 ml bottle, the 5 L water instead of 1.5 L.
- **Missed lines** in long lists and photos.
- **Credit leakage:** orders shipped to customers already over limit.
- **Peak overload:** at 13:00–15:00 the queue backs up and late orders miss the cut-off.

The messages themselves are the hard part: English, Arabic, Arabizi ("3 kartoon pepsi", "mayy 1.5"), roman Urdu/Hindi from shopkeepers ("pepsi ki 2 peti"), house names ("the red one", "small water"), and "same as last week but no milk".

## What we will build (v1)
A desk tool, not an autopilot. Messages are read and turned into draft orders with evidence for every line. An order-taker confirms or fixes them in a fast console, and confirmed orders post to the ERP with a templated WhatsApp confirmation to the retailer. Credit holds are enforced by the system and released by the credit controller.

## How we'll know it worked
| Measure | Today (brief) | v1 target | How we'll measure |
|---|---|---|---|
| Minutes per order keyed | 6–10 | under 2 for typical orders | console timing logs in shadow mode |
| Lines wrong at confirmation | "a few percent" | measurably lower | eval line accuracy; disputes logged in pilot |
| Orders shipped over credit | happens weekly | zero | credit holds are enforced in code |
| Orders missing cut-off at peak | several a day | none from desk backlog | queue age at 16:00 |

## Constraints and risks
- **No change for retailers.** They keep using WhatsApp the way they do now. Anything that asks them to use a form fails.
- **Customer data.** Phone numbers and order history are personal and commercial data. They stay in the customer's database, with retention and access rules (`data-handling.md`, written in P7).
- **The model will be wrong sometimes.** v1 never posts without a human. Auto-confirm is a later decision, made only on measured error rates (`rollout-plan.md`).
- **ERP integration.** The real ERP's API is undocumented in places. v1 talks to an adapter with an idempotency key, so retries can't double-book.
- **Arabic and right-to-left text** must render correctly in the console, or order-takers won't trust it.

## Out of scope for v1
Voice notes (they need speech-to-text), auto-confirm without a human, free-form AI replies to customers, delivery routing, payments.

## Open questions for week 2
- What share of orders arrive as photos? (It decides how much effort goes into image reading.)
- Which units does the ERP accept per SKU, and who maintains pack sizes?
- Can the credit controller work from the same console, or does she need email alerts?
