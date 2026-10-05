# Rollout plan: shadow, assist, then (maybe) auto-confirm

*Fictional engagement. Gates are written as numbers to measure, not promises. The eval numbers quoted are from [`docs/results/eval.md`](../results/eval.md), on synthetic messages. The point of stage 1 is to replace them with numbers from real ones.*

## The principle

Each stage widens what the system does on its own, and each has an exit gate measured on the client's real messages. Every stage can be reversed with one setting. Nobody moves to the next stage because the last one "felt fine".

| Stage | What Orderdesk does | What people do | Reversal |
|---|---|---|---|
| 0. Pilot setup | Reads a copy of the WhatsApp traffic; nothing posts | Nothing changes | Turn off the webhook |
| 1. Shadow (2 weeks) | Drafts every order; never posts | Key orders the old way; one order-taker also confirms Orderdesk's drafts, which are then scored against what was keyed | Turn off the webhook |
| 2. Assist (4+ weeks) | Drafts every order; posts what a person confirms | Confirm or fix drafts instead of keying | ERP posting off: back to keying, drafts still useful as a reading aid |
| 3. Auto-confirm, narrow | Posts orders that clear a measured threshold, from a list of customers who agreed, with every line from their history | Spot-check a sample daily; everything else as in stage 2 | Threshold to 1.0 (nothing auto-confirms) |

## Stage 1: shadow

**Goal:** the eval, repeated on real traffic. The synthetic test set and the hand-written set disagree by 13 points on lines found (93.5% vs 80.5% for Sonnet), so the real number is unknown until it's measured.

- Route a copy of both WhatsApp numbers to Orderdesk (Cloud API webhook; the shared phones keep working).
- The order-takers key orders into the ERP as today. The ERP orders become the ground truth for Orderdesk's drafts, with the same deterministic scorer as the eval (`api/evals/score.py`).
- One order-taker per shift also works the drafts in the console. This measures minutes per order and which lines people change.
- **Data collected:** line accuracy by language style and channel, the error taxonomy, minutes per order in the console vs keying, unit words per product (for the packaging fix in the [week-2 plan](week-2-plan.md)), aliases taught.

**Exit gate to stage 2** (all of them):

| Measure | Gate | Why this level |
|---|---|---|
| Lines correct, real traffic, Sonnet | ≥ 90% | Below that, checking a draft is not faster than keying it |
| Minutes per order in the console | < half of keying, measured on the same orders | The business case in the discovery memo |
| Credit holds | 100% of over-limit orders held | Enforced in code; this checks the balance feed |
| ERP posts | 0 duplicates under fault injection on the client's ERP sandbox | The idempotency key must hold on their system, not just the mock |
| Order-takers | The desk lead signs off | They are the users; a faster tool nobody trusts doesn't get used |

## Stage 2: assist

Orderdesk becomes the way orders are keyed. A person confirms every order, so the system's errors are caught at the desk instead of at delivery.

- **Watch:** disputes per 100 orders (from the delivery team's log), minutes per order, the share of lines people edit, aliases taught per week (it should fall as the vocabulary is learned), queue age at 15:30 against the 16:00 cut-off.
- **Weekly:** re-fit the confidence model on the confirmed orders (`evals.calibrate` on the real split), and re-run the eval on the week's traffic. Fixes go through the same eval before they deploy. A 20-conversation smoke eval in CI is on the week-2 list.

**Exit gate to stage 3:** measured on at least four weeks of stage-2 data, out of sample (fit on weeks 1–3, measure on week 4):

| Measure | Gate |
|---|---|
| Error rate among orders the threshold would auto-confirm | ≤ 1% of those orders wrong in any way, with the upper end of the 95% interval ≤ 2% |
| Share of orders that would auto-confirm | ≥ 15% (below that, the saving isn't worth the risk and the complexity) |
| Disputes per 100 orders | not higher than in the stage-2 baseline |
| Operations manager and credit controller | Sign off in writing, with the customer list |

**Where the synthetic eval stands against that gate** (to show the size of the gap, not to decide anything): with Sonnet, a 0.95 threshold would let 12% of test conversations skip review, and 2.9% of those are not exactly right. Both are on the wrong side of the gate. The confidence model can't yet pick out a large, near-error-free tier, which is why stage 3 is conditional.

## Stage 3: narrow auto-confirm

Only when the gate is met, and only for:

- customers who agreed to it (salesmen ask, because the relationship is theirs);
- orders where every line comes from the customer's history (repeat orders, or usual products in usual sizes), with no holds, no unusual quantity, no out-of-stock line and no photo;
- order values under the supervisor threshold (AED 5,000).

Each auto-confirmed order still gets the template reply. A person spot-checks a random 10% sample daily. The threshold is a setting, and setting it to 1.0 turns the stage off.

**Stop conditions** (any one sends the desk back to stage 2 until the cause is understood): a dispute traced to an auto-confirmed order, the daily sample error rate above 2%, or a change to the catalogue, price lists or model version without a re-run of the eval.

## What would make us stop the whole thing

- Stage 1 shows real-traffic accuracy far below the hand-written set, *and* the alias loop doesn't close the gap within the stage. In that case the product is a reading aid, not a keying tool, and the business case needs redoing.
- Order-takers route around it. That usually means the console is slower than keying for their real orders. Find out why before adding features.
