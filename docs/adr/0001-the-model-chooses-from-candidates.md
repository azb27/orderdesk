# ADR 0001: The model reads and chooses; code computes

**Status:** accepted · **Phase:** P2

## Context
A retailer writes "2 ctn al wadi 500" or sends a photo of a handwritten list. The draft order needs SKU ids, quantities in base units, contract prices, stock checks and a credit check. Any of these can be wrong in a way an order-taker won't notice on a busy morning. A wrong price or a carton read as a piece costs real money, and the ERP will accept it.

## Decision
The work splits into five steps. Only two use the model, and both are boxed in:

1. **Extract** (model, forced tool call): what the customer wrote, line by line. It records the line as written, a plain-English reading of the product, the size words verbatim, the quantity, and the unit normalised to carton, pack or piece. No ids.
2. **Retrieve** (code): candidate SKUs from fuzzy matching, the alias table, the customer's history and learned nicknames. Deterministic: ties are ordered, so the same message gives the same candidates and the same cache key.
3. **Resolve** (model): for each line, pick one id from the candidate list or `NONE`. The tool schema enumerates the allowed ids. Any output that fails validation is rejected, never repaired.
4. **Build** (code): units from the customer's words or their history, base quantities, contract prices in integer fils, stock, credit holds, substitutes.
5. **Confidence** (code): a logistic model over features of steps 2–4, fitted on dev ([ADR 0004](0004-confidence-fitted-on-dev-thresholds-from-test.md)).

## Consequences
- The worst the model can do is choose a wrong product from a plausible shortlist, or say `NONE`. It cannot invent a SKU, a price or a conversion. Every number on the order pad can be traced to code.
- Recall is capped by retrieval: a product missing from the shortlist can't be chosen. The `allcat` ablation (every SKU as a candidate) measures what that cap costs.
- The fuzzy baseline uses its own matcher but the same build step, so prices, units and holds are computed identically. Its lines get confidence 0, so every one is checked.
- When the daily budget is spent or the API fails, the same pipeline runs with fuzzy matching in place of the model, and the draft says so.

## Alternatives considered
- **One prompt that returns the finished order as JSON.** Fewer moving parts, and fine in a demo. But prices and conversions come out of the model, and a plausible wrong number is the most expensive kind of mistake here.
- **Fine-tuning a small model on the generated data.** The data is synthetic, so a fine-tune would learn the generator's habits. Retrieval plus constrained choice transfers to a real catalogue without retraining.
