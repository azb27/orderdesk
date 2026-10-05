"""Build docs/results/eval.md from stored runs (no API calls).

    python -m evals.report

Reads runs/evals/<config>-<split>/results.jsonl and data/eval/truth/. Only complete runs are reported.
Line-level intervals resample whole conversations (lines in one message are not independent).
"""

from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict

import numpy as np
from scipy.stats import binomtest

from evals.calibrate import auc
from orderdesk import config
from orderdesk.parse.confidence import featurize, load_weights, probability
from orderdesk.parse.world import world

OUT = config.ROOT / "docs" / "results" / "eval.md"
OUT_JSON = config.ROOT / "docs" / "results" / "eval_summary.json"
LABELS = {
    "fuzzy": "Fuzzy matching, no model (baseline and API-down fallback)",
    "haiku": "Claude Haiku 4.5 pipeline",
    "sonnet": "Claude Sonnet 5 pipeline",
    "haiku_sonnet": "Haiku 4.5 extracts, Sonnet 5 resolves",
    "nohistory_sonnet": "Sonnet 5, no customer history or nicknames (ablation)",
    "allcat_sonnet": "Sonnet 5, no retrieval: whole catalogue in the prompt (ablation)",
    "nohistory_haiku": "Haiku 4.5, no customer history or nicknames (ablation)",
    "allcat_haiku": "Haiku 4.5, no retrieval: whole catalogue in the prompt (ablation)",
}
STYLE = {"en": "English", "ar": "Arabic script", "arabizi": "Arabizi", "roman": "Roman Hindi/Urdu"}
W = world()


def load_truth(split: str) -> dict[str, dict]:
    return {t["id"]: t for t in map(json.loads, (config.TRUTH / f"{split}.jsonl").read_text().splitlines())}


def load_runs(split: str, truth: dict[str, dict]) -> dict[str, dict[str, dict]]:
    out = {}
    for name in LABELS:
        p = config.RUNS / "evals" / f"{name}-{split}" / "results.jsonl"
        if not p.exists():
            continue
        rows = {r["id"]: r for r in map(json.loads, p.read_text().splitlines()) if not r.get("error")}
        if set(rows) >= set(truth) or (name.startswith(("nohistory", "allcat")) and len(rows) >= 50):
            out[name] = rows
    return out


def boot(ids: list[str], f, n: int = 2000, seed: int = 7) -> tuple[float, float, float]:
    rng = np.random.default_rng(seed)
    point = f(ids)
    draws = [f([ids[i] for i in rng.integers(0, len(ids), len(ids))]) for _ in range(n)]
    lo, hi = np.quantile(draws, [0.025, 0.975])
    return point, float(lo), float(hi)


def pct(t) -> str:
    return f"**{100 * t[0]:.1f}%** [{100 * t[1]:.1f}, {100 * t[2]:.1f}]"


def summary(rows: dict[str, dict], ids: list[str]) -> dict:
    def recall(xs):
        return sum(rows[i]["score"]["n_right"] for i in xs) / max(
            1, sum(rows[i]["score"]["n_truth"] for i in xs)
        )

    def precision(xs):
        return sum(rows[i]["score"]["n_right"] for i in xs) / max(
            1, sum(rows[i]["score"]["n_pred"] for i in xs)
        )

    def exact(xs):
        return float(np.mean([rows[i]["score"]["exact"] for i in xs]))

    risk = sum(rows[i]["score"]["money_at_risk_fils"] for i in ids) / max(
        1, sum(rows[i]["score"]["order_value_fils"] for i in ids)
    )
    lat = [rows[i]["latency_s"] for i in ids]
    cost = [rows[i].get("cost_usd", 0.0) for i in ids]
    return {"recall": boot(ids, recall), "precision": boot(ids, precision), "exact": boot(ids, exact), "money_at_risk": risk,
            "cost_per_conv": float(np.mean(cost)), "total_cost": float(np.sum(cost)), "p50": float(np.median(lat)),
            "p95": float(np.quantile(lat, 0.95)), "errors": sum(1 for i in ids if rows[i].get("error")), "n": len(ids)}  # fmt: skip


def truth_line_table(truth: dict[str, dict], rows: dict[str, dict]) -> list[dict]:
    out = []
    for cid, t in truth.items():
        r = rows.get(cid)
        if r is None:
            continue
        for ln in t["lines"]:
            out.append(
                {
                    **ln,
                    "conv": cid,
                    "kind": t["kind"],
                    "channel": r["channel"],
                    "right": r["score"]["truth_right"].get(ln["sku"], False),
                }
            )
    return out


def taxonomy(truth: dict[str, dict], rows: dict[str, dict]) -> dict[str, int]:
    """Why each line was wrong: missed, wrong size, wrong product, wrong unit, wrong number, extra."""
    c: dict[str, int] = defaultdict(int)
    for cid, t in truth.items():
        if cid not in rows:
            continue
        tl = {ln["sku"]: ln["qty_base"] for ln in t["lines"]}
        pl = {
            ln["sku"]: ln["qty_base"]
            for ln in rows[cid]["lines"]
            if ln.get("sku") and ln.get("qty_base", 0) > 0
        }
        un_t = [k for k in tl if k not in pl]
        un_p = [k for k in pl if k not in tl]
        for k, tq in tl.items():
            if k in pl and pl[k] != tq:
                s = W.skus[k]
                ratio = {pl[k] / tq, tq / pl[k]}
                c[
                    "wrong unit (carton vs pack vs piece)"
                    if ratio & {s["carton_size"], s["pack_size"] or -1}
                    else "wrong number"
                ] += 1
        for k in un_t:
            fam, cat = W.skus[k]["family"], W.skus[k]["category"]
            same_fam = next((p for p in un_p if W.skus[p]["family"] == fam), None)
            same_cat = next((p for p in un_p if W.skus[p]["category"] == cat), None)
            if same_fam:
                c["wrong size"] += 1
                un_p.remove(same_fam)
            elif same_cat:
                c["wrong product or variant"] += 1
                un_p.remove(same_cat)
            else:
                c["missed line"] += 1
        c["extra line (not ordered)"] += len(un_p)
    return dict(sorted(c.items(), key=lambda kv: -kv[1]))


def confidence_points(rows: dict[str, dict], w: dict) -> tuple[np.ndarray, np.ndarray]:
    ps, ys = [], []
    for r in rows.values():
        right = r["score"]["pred_right"]
        for ln in r["lines"]:
            if ln.get("sku") in right:
                ps.append(probability(featurize({"features": ln.get("features") or {}}, ln["flags"]), w))
                ys.append(float(right[ln["sku"]]))
    return np.array(ps), np.array(ys)


def touchless(ps: np.ndarray, ys: np.ndarray, max_err: float) -> tuple[float, float, float]:
    """Largest share of predicted lines a threshold can auto-accept with error among them <= max_err."""
    order = np.argsort(-ps)
    errs = np.cumsum(1 - ys[order])
    n = np.arange(1, len(ps) + 1)
    ok = np.flatnonzero(errs / n <= max_err)
    if not len(ok):
        return 0.0, float("nan"), 1.0
    k = ok[-1]
    return float((k + 1) / len(ps)), float(errs[k] / (k + 1)), float(ps[order][k])


def mcnemar(a: list[bool], b: list[bool]) -> tuple[int, int, float]:
    only_a = sum(x and not y for x, y in zip(a, b, strict=True))
    only_b = sum(y and not x for x, y in zip(a, b, strict=True))
    p = binomtest(only_a, only_a + only_b, 0.5).pvalue if only_a + only_b else 1.0
    return only_a, only_b, float(p)


def main() -> None:
    weights, wsrc = load_weights()
    test_truth = load_truth("test")
    runs = load_runs("test", test_truth)
    gold_truth = load_truth("gold")
    gold = load_runs("gold", gold_truth)
    summ = {n: summary(r, sorted(set(r) & set(test_truth))) for n, r in runs.items()}
    L = ["# Orderdesk eval: results", "",
         "Generated by `python -m evals.report` from `runs/evals/*/results.jsonl` (written by `python -m evals.run --config <name> --split <split>`). Do not edit by hand.", "",
         f"*Built {dt.datetime.now():%Y-%m-%d %H:%M}. Test split: {len(test_truth)} conversations, {sum(len(t['lines']) for t in test_truth.values())} order lines, generated by `python -m orderdesk.world.build` with ground truth. "
         "A line is right only when both the SKU and the quantity in base units match. Intervals are 95% bootstraps over conversations.*", "",
         "## Headline (test split)", "",
         "| Configuration | Lines found (recall) | Lines correct (precision) | Orders exactly right | Order value at risk | $ / conversation | p50 / p95 time |",
         "|---|---|---|---|---:|---:|---:|"]  # fmt: skip
    for n, s in summ.items():
        lab = LABELS[n] + (f" (first {s['n']} conversations)" if s["n"] < len(test_truth) else "")
        L.append(f"| {lab} | {pct(s['recall'])} | {pct(s['precision'])} | {pct(s['exact'])} | {100 * s['money_at_risk']:.1f}% | "
                 f"${s['cost_per_conv']:.4f} | {s['p50']:.1f}s / {s['p95']:.1f}s |")  # fmt: skip
    L += [
        "",
        "*Order value at risk*: AED value of wrong, missing and extra lines, divided by the true order value (each customer's own prices).",
    ]
    # slices
    main_cfgs = [n for n in ("fuzzy", "haiku", "sonnet", "haiku_sonnet") if n in runs]
    tables = {n: truth_line_table(test_truth, runs[n]) for n in main_cfgs}

    def slice_rows(title: str, key, values):
        L.extend(["", f"### {title}", "", "| | Lines | " + " | ".join(LABELS[n].split(" (")[0] for n in main_cfgs) + " |",
                  "|---|---:|" + "---:|" * len(main_cfgs)])  # fmt: skip
        for label, pred in values:
            cells, count = [], 0
            for n in main_cfgs:
                sel = [x for x in tables[n] if pred(x)]
                count = len(sel)
                cells.append(f"{100 * np.mean([x['right'] for x in sel]):.1f}%" if sel else "–")
            L.append(f"| {label} | {count} | " + " | ".join(cells) + " |")

    L += ["", "## Where it works and where it doesn't (share of true lines found exactly, test split)"]
    slice_rows(
        "By language style of the line",
        None,
        [(STYLE[s], lambda x, s=s: x["style"] == s and x["via"] != "history") for s in STYLE],
    )
    slice_rows(
        "By channel",
        None,
        [
            ("Text message", lambda x: x["channel"] == "text"),
            ("Photo of a handwritten list", lambda x: x["channel"] == "image"),
        ],
    )
    slice_rows("By how the product was named", None, [
        ("A name in the parser's alias table", lambda x: x["via"] == "term" and x["term_seen"]),
        ("A held-out name the parser has never been given", lambda x: x["via"] == "term" and not x["term_seen"]),
        ("The customer's own nickname", lambda x: x["via"] == "nickname"),
        ("'Same as last order' (from history)", lambda x: x["via"] == "history"),
    ])  # fmt: skip
    slice_rows("By what the customer left out", None, [
        ("Size and unit both written", lambda x: x["via"] == "term" and x["size_given"] and x["unit_given"]),
        ("Size left out (only their history says which)", lambda x: x["via"] == "term" and not x["size_given"]),
        ("Unit left out (only their history says carton or piece)", lambda x: x["via"] == "term" and not x["unit_given"]),
    ])  # fmt: skip
    slice_rows("By conversation type", None, [("New order", lambda x: x["kind"] == "order"), ("Repeat last order with changes", lambda x: x["kind"] == "usual"),
                                               ("Order plus a follow-up message", lambda x: x["kind"] == "amend")])  # fmt: skip
    nots = [cid for cid, t in test_truth.items() if t["kind"] == "not_order"]
    L += ["", "**Not an order** (questions, complaints): conversations correctly left with no lines: " + ", ".join(
        f"{LABELS[n].split(' (')[0]} {sum(runs[n][c]['score']['exact'] for c in nots)}/{len(nots)}" for n in main_cfgs) + "."]  # fmt: skip
    # failure taxonomy
    L += ["", "## Why lines were wrong (test split, counts)", "", "| Error | " + " | ".join(LABELS[n].split(" (")[0] for n in main_cfgs) + " |",
          "|---|" + "---:|" * len(main_cfgs)]  # fmt: skip
    taxes = {n: taxonomy(test_truth, runs[n]) for n in main_cfgs}
    for k in sorted(
        {k for t in taxes.values() for k in t}, key=lambda k: -max(t.get(k, 0) for t in taxes.values())
    ):
        L.append(f"| {k} | " + " | ".join(str(taxes[n].get(k, 0)) for n in main_cfgs) + " |")
    # significance
    if len(main_cfgs) > 1:
        L += [
            "",
            "## Are the differences real?",
            "Exact McNemar test on the same true lines.",
            "",
            "| A vs B | Only A right | Only B right | p |",
            "|---|---:|---:|---:|",
        ]
        pairs = [(a, b) for i, a in enumerate(main_cfgs) for b in main_cfgs[i + 1 :]]
        for n in runs:
            if n.startswith(("nohistory", "allcat")):
                base = n.split("_")[-1]
                if base in runs:
                    pairs.append((base, n))
        for a, b in pairs:
            ids = sorted(set(runs[a]) & set(runs[b]) & set(test_truth))
            ta, tb = (
                truth_line_table({i: test_truth[i] for i in ids}, runs[a]),
                truth_line_table({i: test_truth[i] for i in ids}, runs[b]),
            )
            oa, ob, p = mcnemar([x["right"] for x in ta], [x["right"] for x in tb])
            L.append(
                f"| {LABELS[a].split(' (')[0]} vs {LABELS[b].split(' (')[0]} ({len(ta)} lines) | {oa} | {ob} | {p:.2g} |"
            )
    # confidence and touchless
    L += ["", "## How much could skip a human? (test split)",
          f"Each predicted line gets a probability of being right from a logistic model over its evidence (model's self-rating, exact alias hit, customer history, size match, ...), "
          f"fitted on the **dev** split only (`python -m evals.calibrate`; weights: {wsrc}). The table shows the largest share of lines a single threshold could auto-accept "
          "while keeping the error rate among accepted lines at or below the target.", "",
          "| Configuration | AUC | Auto-accept at ≤ 0.5% error | at ≤ 1% | at ≤ 2% |", "|---|---:|---:|---:|---:|"]  # fmt: skip
    conf = {}
    for n in [x for x in ("haiku", "sonnet", "haiku_sonnet") if x in runs]:
        ps, ys = confidence_points(runs[n], weights)
        conf[n] = {"auc": auc(ps, ys), **{str(k): touchless(ps, ys, k) for k in (0.005, 0.01, 0.02)}}
        L.append(f"| {LABELS[n]} | {conf[n]['auc']:.3f} | " + " | ".join(
            f"{100 * conf[n][str(k)][0]:.0f}% of lines (actual error {100 * conf[n][str(k)][1]:.1f}%)" for k in (0.005, 0.01, 0.02)) + " |")  # fmt: skip
    L += [
        "",
        "Auto-accepting lines is **not** switched on in v1: every order is confirmed by a person. This table is the evidence the rollout plan uses to decide when it could be.",
    ]
    # gold
    if gold:
        L += ["", "## Hand-written set (40 conversations, not from the generator)", "",
              "| Configuration | Lines found | Lines correct | Orders exactly right |", "|---|---|---|---|"]  # fmt: skip
        for n, r in gold.items():
            s = summary(r, sorted(set(r) & set(gold_truth)))
            L.append(f"| {LABELS[n]} | {pct(s['recall'])} | {pct(s['precision'])} | {pct(s['exact'])} |")
    L += ["", "## How to read this",
          "- **The test set is synthetic.** Messages come from a generator with known answers. It is varied (four language styles, typos, photos, history-dependent lines, held-out names), "
          "but a generator can't surprise its author the way real customers do. The held-out-name slice and the hand-written set measure how much the score depends on that.",
          "- **One run per configuration.** Model outputs vary between runs; small differences sit inside the intervals.",
          "- **The confidence model was fitted on dev, reported on test**, so the touchless numbers are out-of-sample.",
          "- **Costs** are list prices for the tokens used, with prompt caching on. Re-runs hit a local response cache and cost $0; the table reports the first run's cost."]  # fmt: skip
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L) + "\n")
    OUT_JSON.write_text(
        json.dumps({"summary": summ, "confidence": conf, "taxonomy": taxes}, indent=1, default=float) + "\n"
    )
    print(f"wrote {OUT}")
    for n, s in summ.items():
        print(
            f"{n:18s} recall {100 * s['recall'][0]:.1f}  precision {100 * s['precision'][0]:.1f}  exact {100 * s['exact'][0]:.1f}  ${s['total_cost']:.2f}"
        )


if __name__ == "__main__":
    main()
