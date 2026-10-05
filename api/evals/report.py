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
from orderdesk.parse.build import REVIEW_FLAGS, unusual_qty
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


def load_archive(tag: str, split: str, truth: dict[str, dict]) -> dict[str, dict[str, dict]]:
    out = {}
    for name in LABELS:
        p = config.RUNS / "evals" / "_archive" / tag / f"{name}-{split}" / "results.jsonl"
        if p.exists():
            rows = {r["id"]: r for r in map(json.loads, p.read_text().splitlines()) if not r.get("error")}
            if set(rows) >= set(truth):
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


def classify(truth_lines: list[dict], pred_lines: list[dict]) -> list[tuple[str, str | None, str | None]]:
    """Every error in one conversation as (kind, truth sku, predicted sku): missed, wrong size, wrong product,
    wrong unit, wrong number, extra. A wrong line is matched to a leftover prediction in the same family first."""
    tl = {ln["sku"]: ln["qty_base"] for ln in truth_lines}
    pl = {ln["sku"]: ln["qty_base"] for ln in pred_lines if ln.get("sku") and ln.get("qty_base", 0) > 0}
    out: list[tuple[str, str | None, str | None]] = []
    un_t = [k for k in tl if k not in pl]
    un_p = [k for k in pl if k not in tl]
    for k, tq in tl.items():
        if k in pl and pl[k] != tq:
            s = W.skus[k]
            ratio = {pl[k] / tq, tq / pl[k]}
            unit = ratio & {s["carton_size"], s["pack_size"] or -1}
            out.append(("wrong unit (carton vs pack vs piece)" if unit else "wrong number", k, k))
    for k in un_t:
        fam, cat = W.skus[k]["family"], W.skus[k]["category"]
        same_fam = next((p for p in un_p if W.skus[p]["family"] == fam), None)
        same_cat = next((p for p in un_p if W.skus[p]["category"] == cat), None)
        if same_fam:
            out.append(("wrong size", k, same_fam))
            un_p.remove(same_fam)
        elif same_cat:
            out.append(("wrong product or variant", k, same_cat))
            un_p.remove(same_cat)
        else:
            out.append(("missed line", k, None))
    out += [("extra line (not ordered)", None, p) for p in un_p]
    return out


def taxonomy(truth: dict[str, dict], rows: dict[str, dict]) -> dict[str, int]:
    """Why each line was wrong, counted over a run."""
    c: dict[str, int] = defaultdict(int)
    for cid, t in truth.items():
        if cid in rows:
            for kind, _, _ in classify(t["lines"], rows[cid]["lines"]):
                c[kind] += 1
    return dict(sorted(c.items(), key=lambda kv: -kv[1]))


def line_points(rows: dict[str, dict], w: dict, truth: dict[str, dict]) -> list[dict]:
    """Every predicted line with its confidence, whether it is right, and whether a rule forces a look."""
    out = []
    for cid, r in rows.items():
        right = r["score"]["pred_right"]
        cust = truth[cid]["customer"] if cid in truth else None
        for ln in r["lines"]:
            if ln.get("sku") in right:
                flags = list(ln["flags"])
                if cust and unusual_qty(W, cust, ln["sku"], ln["qty_base"]) and "unusual_qty" not in flags:
                    flags.append("unusual_qty")  # the guard was added after these runs; apply it the same way
                out.append({"id": cid, "p": probability(featurize({"features": ln.get("features") or {}}, flags), w),
                            "right": bool(right[ln["sku"]]), "forced": any(f in REVIEW_FLAGS for f in flags)})  # fmt: skip
    return out


def confidence_points(
    rows: dict[str, dict], w: dict, truth: dict[str, dict]
) -> tuple[np.ndarray, np.ndarray]:
    pts = line_points(rows, w, truth)
    return np.array([x["p"] for x in pts]), np.array([float(x["right"]) for x in pts])


def at_threshold(pts: list[dict], t: float) -> tuple[float, float]:
    """Share of predicted lines a threshold auto-accepts, and the error rate among them. Flagged lines never are."""
    acc = [x for x in pts if x["p"] >= t and not x["forced"]]
    if not acc:
        return 0.0, float("nan")
    return len(acc) / len(pts), 1 - float(np.mean([x["right"] for x in acc]))


def touchless(pts: list[dict], max_err: float) -> tuple[float, float, float] | None:
    """Largest share a single threshold auto-accepts with error <= max_err. Lines with equal confidence go together:
    a threshold can't split them. None if no threshold gets there."""
    best = None
    for t in sorted({x["p"] for x in pts}, reverse=True):
        share, err = at_threshold(pts, t)
        if share and err <= max_err and (best is None or share > best[0]):
            best = (share, err, t)
    return best


def orders_at_threshold(rows: dict[str, dict], pts: list[dict], t: float) -> tuple[float, float]:
    """Share of orders that would skip review (every line clears the threshold, nothing unresolved, no holds),
    and the share of those that are not exactly right."""
    by_id: dict[str, list[dict]] = defaultdict(list)
    for x in pts:
        by_id[x["id"]].append(x)
    skip, wrong = 0, 0
    for cid, r in rows.items():
        lines = by_id.get(cid, [])
        if (
            r.get("intent") not in ("order", "repeat_last_order")
            or not lines
            or r.get("holds")
            or len(lines) != len(r["lines"])
        ):
            continue
        if all(x["p"] >= t and not x["forced"] for x in lines):
            skip += 1
            wrong += not r["score"]["exact"]
    return skip / len(rows), (wrong / skip if skip else float("nan"))


def guard_effect(rows: dict[str, dict], truth: dict[str, dict]) -> dict[str, float]:
    """What the unusual-quantity flag catches: flagged lines right/wrong, and the share of the value at risk on
    predicted lines that sits on flagged lines."""
    fr = fw = 0
    risk = caught = 0
    for cid, r in rows.items():
        t = {ln["sku"]: ln["qty_base"] for ln in truth[cid]["lines"]}
        cust = W.customers[truth[cid]["customer"]]
        for ln in r["lines"]:
            sku, b = ln.get("sku"), ln.get("qty_base") or 0
            if not sku or b <= 0:
                continue
            right = t.get(sku) == b
            flagged = unusual_qty(W, cust["id"], sku, b)
            fr += flagged and right
            fw += flagged and not right
            if not right:
                v = abs(t.get(sku, 0) - b) * W.price_fils(cust, sku)
                risk += v
                caught += v if flagged else 0
    return {"flagged_right": fr, "flagged_wrong": fw, "risk_caught": caught / risk if risk else 0.0}


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
    for n, s in list(summ.items()):
        abl = n.startswith(("nohistory", "allcat"))
        if abl and n.split("_")[-1] in runs and f"paired_{n.split('_')[-1]}" not in summ:
            base = n.split("_")[-1]
            ps = summary(runs[base], sorted(set(runs[n]) & set(runs[base]) & set(test_truth)))
            summ[f"paired_{base}"] = ps
            L.append(f"| {LABELS[base]}, same {ps['n']} conversations as the ablations below | {pct(ps['recall'])} | {pct(ps['precision'])} | "
                     f"{pct(ps['exact'])} | {100 * ps['money_at_risk']:.1f}% | ${ps['cost_per_conv']:.4f} | {ps['p50']:.1f}s / {ps['p95']:.1f}s |")  # fmt: skip
        lab = LABELS[n] + (f" ({s['n']} conversations)" if s["n"] < len(test_truth) else "")
        cost = f"${s['cost_per_conv']:.4f}†" if abl else f"${s['cost_per_conv']:.4f}"
        time_ = f"{s['p50']:.1f}s / {s['p95']:.1f}s" + ("†" if abl else "")
        L.append(
            f"| {lab} | {pct(s['recall'])} | {pct(s['precision'])} | {pct(s['exact'])} | {100 * s['money_at_risk']:.1f}% | {cost} | {time_} |"
        )
    L += [
        "",
        "*Order value at risk*: AED value of wrong, missing and extra lines, divided by the true order value (each customer's own prices). "
        'It can pass 100%: fuzzy matching reads a size such as "450 g" as 450 cartons, and one such line outweighs the order (see *Quantity guard* below).',
        "",
        "† The ablations reuse the Sonnet run's cached extraction step, so their cost and time cover only the step they change.",
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
          f"fitted on the **dev** split of the Sonnet run only (`python -m evals.calibrate --config sonnet`; weights: {wsrc}). Lines with a review flag "
          "(out of stock, unit guessed, unusual quantity) are never auto-accepted. A threshold can't separate lines with the same evidence, so ties move together.", "",
          "### Lines", "",
          "| Configuration | AUC | Most lines auto-accepted with ≤ 1% of them wrong | ≤ 2% | ≤ 3% |", "|---|---:|---:|---:|---:|"]  # fmt: skip
    conf = {}
    cfgs = [x for x in ("haiku", "sonnet", "haiku_sonnet") if x in runs]
    pts = {n: line_points(runs[n], weights, test_truth) for n in cfgs}

    def cell(b: tuple[float, float, float] | None) -> str:
        return (
            "none" if b is None else f"{100 * b[0]:.0f}% of lines ({100 * b[1]:.1f}% wrong, p ≥ {b[2]:.3f})"
        )

    for n in cfgs:
        ps = np.array([x["p"] for x in pts[n]])
        ys = np.array([float(x["right"]) for x in pts[n]])
        conf[n] = {"auc": auc(ps, ys), **{str(k): touchless(pts[n], k) for k in (0.01, 0.02, 0.03)}}
        L.append(
            f"| {LABELS[n]} | {conf[n]['auc']:.3f} | "
            + " | ".join(cell(conf[n][str(k)]) for k in (0.01, 0.02, 0.03))
            + " |"
        )
    L += ["", "### Whole orders", "",
          "An order skips review only if every line clears the threshold and it has no hold (credit, unresolved line, unknown number). "
          "The question for the desk: how many orders would nobody read, and how many of those would be wrong?", "",
          "| Configuration | Threshold | Conversations nobody reads (share of all) | Of those, not exactly right |", "|---|---:|---:|---:|"]  # fmt: skip
    for n in cfgs:
        for t in (0.85, 0.9, 0.93, 0.95):
            sh, wr = orders_at_threshold(runs[n], pts[n], t)
            conf[n][f"orders@{t}"] = (sh, wr)
            L.append(
                f"| {LABELS[n]} | {t:.2f} | {100 * sh:.0f}% | "
                + ("–" if np.isnan(wr) else f"{100 * wr:.1f}%")
                + " |"
            )
    L += [
        "",
        "Auto-accepting is **not** switched on in v1: every order is confirmed by a person. These tables are the evidence the rollout plan "
        "uses to decide when it could be, after the same measurement on real messages in shadow mode.",
    ]
    # the quantity guard
    dev_truth = load_truth("dev")
    dev = load_runs("dev", dev_truth)
    L += ["", "## Quantity guard", "",
          "`parse.build.unusual_qty` flags a line for a look when it asks for more than 3× the most of that product the customer has ever ordered, "
          "or, for a product they have never ordered, more than half the value of their largest order. The two thresholds were set on **dev**; "
          "test is reported as is. It was added after the runs, and is applied here to the stored lines exactly as the app applies it.", "",
          "| Configuration | Split | Lines flagged that were right (needless look) | Flagged and wrong | Share of value at risk on flagged lines |",
          "|---|---|---:|---:|---:|"]  # fmt: skip
    guard = {}
    for split, rs, tr in (("dev", dev, dev_truth), ("test", runs, test_truth)):
        for n in [x for x in ("fuzzy", "haiku", "sonnet") if x in rs]:
            g = guard_effect(rs[n], tr)
            guard[f"{n}-{split}"] = g
            L.append(
                f"| {LABELS[n]} | {split} | {g['flagged_right']} | {g['flagged_wrong']} | {100 * g['risk_caught']:.0f}% |"
            )
    # what the failure analysis changed
    L += ["", "## What the failure analysis changed", "",
          "The first full runs are archived in `runs/evals/_archive/v1/`. Reading their errors (`docs/results/failures.md`, and "
          "`docs/engagement/failure-analysis.md` for the write-up) led to two fixes in code, not in prompts:", "",
          "1. **Size from history.** When no size is written and the customer has only ever bought one size of the chosen product, "
          "use that size (`size_from_history` flag). The resolve prompt already said this; the model didn't always follow it.",
          "2. **Removals by product, not size.** \"No milk\" on a repeat order removes the milk they had last time even if the model "
          "picked a different size of it.", "",
          "Prompts are unchanged, so every model call was a cache hit: `python -m evals.run --config <name> --split <split> --rebuild v1` "
          "re-measures the same model outputs with the new code. **Caveat:** the errors that motivated the fixes were read on dev and test, "
          "so the test gain is not a clean holdout. Dev moves the same way. The hand-written set doesn't move: none of its lines hit either case. Fuzzy matching doesn't move: the size rule lives in the model pipeline, and none of its removals picked a different size.", "",
          "| Configuration | Split | Lines correct, first run | After fixes | Orders exactly right, first run | After fixes | Lines only first run got right | Only after fixes | p |",
          "|---|---|---:|---:|---:|---:|---:|---:|---:|"]  # fmt: skip
    for split in ("dev", "test", "gold"):
        tr = {"dev": load_truth("dev"), "test": test_truth, "gold": gold_truth}[split]
        cur = {"dev": load_runs("dev", tr), "test": runs, "gold": gold}[split]
        old = load_archive("v1", split, tr)
        for n in [x for x in ("fuzzy", "haiku", "sonnet") if x in cur and x in old]:
            ids = sorted(set(cur[n]) & set(old[n]) & set(tr))
            a, b = summary(old[n], ids), summary(cur[n], ids)
            ta = truth_line_table({i: tr[i] for i in ids}, old[n])
            tb = truth_line_table({i: tr[i] for i in ids}, cur[n])
            oa, ob, p = mcnemar([x["right"] for x in ta], [x["right"] for x in tb])
            L.append(f"| {LABELS[n].split(' (')[0]} | {split} | {100 * a['precision'][0]:.1f}% | {100 * b['precision'][0]:.1f}% | "
                     f"{100 * a['exact'][0]:.1f}% | {100 * b['exact'][0]:.1f}% | {oa} | {ob} | {p:.2g} |")  # fmt: skip
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
          "- **The confidence model was fitted on dev, reported on test**, so the touchless numbers are out-of-sample. It was fitted on Sonnet's lines; "
          "applied to Haiku it is a transfer, which is part of why Haiku's numbers are lower.",
          "- **Costs** are list prices for the tokens used, with prompt caching on. Re-runs hit a local response cache and cost $0; the table reports the first run's cost."]  # fmt: skip
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L) + "\n")
    OUT_JSON.write_text(
        json.dumps(
            {"summary": summ, "confidence": conf, "taxonomy": taxes, "guard": guard}, indent=1, default=float
        )
        + "\n"
    )
    print(f"wrote {OUT}")
    for n, s in summ.items():
        print(
            f"{n:18s} recall {100 * s['recall'][0]:.1f}  precision {100 * s['precision'][0]:.1f}  exact {100 * s['exact'][0]:.1f}  ${s['total_cost']:.2f}"
        )


if __name__ == "__main__":
    main()
