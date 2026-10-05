"""Deterministic scoring of a draft against ground truth. No LLM judge.

A predicted line is right when its SKU and base-unit quantity both match a truth line. A wrong quantity
counts against precision and recall, like a wrong SKU: either way the warehouse picks the wrong thing.
"""

from __future__ import annotations

from orderdesk.parse.world import World


def score(truth: dict, pred_lines: list[dict], intent: str, world: World) -> dict:
    t = {ln["sku"]: ln["qty_base"] for ln in truth["lines"]}
    p = {ln["sku"]: ln["qty_base"] for ln in pred_lines if ln.get("sku") and ln.get("qty_base", 0) > 0}
    right = {k for k, v in p.items() if t.get(k) == v}
    cust = world.customers.get(truth["customer"])

    def value(sku: str, base: int) -> int:
        return (world.price_fils(cust, sku) if cust else world.skus[sku]["price_fils"]) * base

    at_risk = sum(
        abs(value(k, t.get(k, 0)) - value(k, p.get(k, 0))) for k in set(t) | set(p) if t.get(k) != p.get(k)
    )
    if truth["kind"] == "not_order":
        exact = not p and intent == "not_order"
    else:
        exact = p == t
    return {
        "n_truth": len(t),
        "n_pred": len(p),
        "n_right": len(right),
        "exact": exact,
        "money_at_risk_fils": at_risk,
        "order_value_fils": sum(value(k, v) for k, v in t.items()),
        "truth_right": {k: k in right for k in t},  # per truth line, for slices
        "pred_right": {k: k in right for k in p},  # per predicted line, for confidence analysis
        "sku_right_qty_wrong": sum(1 for k in p if k in t and t[k] != p[k]),
    }
