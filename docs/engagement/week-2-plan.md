# Week 2 plan

*What the engagement does next, in priority order, and why. Each item names the evidence that put it on the list. Fictional client, real reasoning.*

## Goal for the week

Turn the synthetic eval into a real one, and fix the error class the hand-written set exposed. At the end of the week, Saffron Lane should know Orderdesk's accuracy on its own messages, not on ours.

## 1. Get real messages flowing (shadow mode, stage 1 of the [rollout plan](rollout-plan.md))

**Why:** the synthetic test set says 93.5% of lines are found exactly; the hand-written set says 80.5%. Only real traffic settles which is closer.

- With IT, add Orderdesk's webhook to the Meta app on both WhatsApp numbers. Finish `Sender`'s cloud mode, and fetch media from the Graph API instead of the simulator store.
- Nightly export of the day's keyed ERP orders as ground truth. Score each draft with `api/evals/score.py` against the ERP order the order-taker actually keyed.
- Owner: engagement engineer + IT admin. Done when a day's traffic is scored end to end.

## 2. Resolve unit words against the product's packaging

**Why:** this is the largest error class on the hand-written set ([failure analysis](failure-analysis.md), pattern 5). "4 boxes" of a product sold by the box is 4 pieces, not 4 cartons. The extraction prompt can't know which products are sold by the box; the catalogue can.

- Extraction keeps the customer's unit word verbatim (`unit_word`) alongside its guess.
- Code maps the word using the SKU's packaging. A word that names the product's own packaging (box, bag, jar, tray, ربطة) means the base unit; ctn, case, peti, kartoon mean the carton.
- Measure on the real shadow-mode traffic first, then on the eval sets as regression checks. The hand-written set stays untouched by tuning.
- This changes a prompt, so it is a paid run: about $1.90 for dev and $6.40 for test with Sonnet, going by the first runs.

## 3. Seed the alias table from the client's history

**Why:** shop vocabulary ("6aqa", "mai ghazi", "3aish") is the largest error class among the model's choices, and it is local to this client's customers.

- Pull 12 months of WhatsApp threads alongside the ERP orders keyed from them. Align the words to SKUs with the same retrieval code, and have the desk lead review the top 200 new aliases in an afternoon.
- The eval's held-out names stay held out. This is about the client's words, not the generator's.

## 4. Two small prompt fixes, measured on their own

**Why:** both are named in the failure analysis, and each is cheap to test in isolation.

- Tell the resolver that a removal needs a product too. It answered NONE for "anda brown nahi chahiye" because it read a removal as a negation.
- Tell the extractor that a unit word with no number means one ("زيت ١٫٥ لتر كرتون" is one carton).

## 5. Put the eval in CI

**Why:** every fix this week touches the parser, and a 20-conversation smoke run catches regressions before a deploy, as it does in Stockroom.

- A fixed 20-conversation subset of dev, run through the cache, so it costs nothing unless a prompt changed. Compare it with a stored baseline and fail the build if lines found drop by more than one line.

## 6. Answer the discovery memo's open questions

| Question | How we'll answer it |
|---|---|
| What share of orders arrive as photos? | Count them in shadow-mode traffic. Photo lines are 88% right against 94.5% for text on the synthetic set (Sonnet), so the share decides how much week-3 effort goes there |
| Which units does the ERP accept per SKU, and who maintains pack sizes? | IT admin + an ERP export; needed for item 2 |
| Can the credit controller work from the console? | Sit with her for an hour on day 2. Supervisor confirmation of held orders is already built; the question is whether she wants alerts |

## Not this week

- Auto-confirm, in any form. The [rollout plan](rollout-plan.md) gates it on four weeks of assist-mode data.
- Voice notes, delivery routing, payments: out of scope for v1.
- Swapping models. Sonnet is the choice on the evidence so far. Revisit only with real-traffic numbers.
