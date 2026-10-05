"""Run a parser configuration over an eval split. Resumable; stops starting new conversations past a budget.

    python -m evals.run --config sonnet --split test [--budget 10] [--workers 4] [--limit N]

Results: runs/evals/<config>-<split>/results.jsonl (one row per conversation). The model cache in
runs/llm_cache makes a re-run of an unchanged config free and identical.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from evals.score import score
from orderdesk import config
from orderdesk.parse.fuzzy import parse_text
from orderdesk.parse.llm import Claude
from orderdesk.parse.pipeline import parse_conversation
from orderdesk.parse.world import World, world

CONFIGS = {
    "fuzzy": {"model": None},
    "sonnet": {"model": config.MODEL},
    "haiku": {"model": config.CHEAP_MODEL},
    "haiku_sonnet": {"model": config.CHEAP_MODEL, "resolve_model": config.MODEL},
    "nohistory": {"model": None, "no_history": True},  # model filled from --base
    "allcat": {"model": None, "mode": "all"},
}
_lock = threading.Lock()


def no_memory(w: World) -> World:
    """The same distributor with no order history and no learned nicknames (ablation)."""
    customers = {k: {**c, "nicknames": {}} for k, c in w.customers.items()}
    return World(w.skus, customers, w.by_phone, {}, w.stock, w.aliases)


def load(split: str) -> tuple[list[dict], dict[str, dict]]:
    convs = [json.loads(x) for x in (config.EVAL / split / "conversations.jsonl").read_text().splitlines()]
    truth = {t["id"]: t for t in map(json.loads, (config.TRUTH / f"{split}.jsonl").read_text().splitlines())}
    return convs, truth


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, choices=sorted(CONFIGS))
    ap.add_argument("--base", default="sonnet", choices=["sonnet", "haiku"], help="model for the ablations")
    ap.add_argument("--split", default="test", choices=["dev", "test", "gold"])
    ap.add_argument("--budget", type=float, default=10.0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--rebuild", metavar="TAG", help="archive the current results under runs/evals/_archive/TAG and run "
                    "everything again; with unchanged prompts every model call is a cache hit, so this re-measures code "
                    "changes for $0 and keeps each row's first-run cost and time")  # fmt: skip
    a = ap.parse_args()
    cfg = dict(CONFIGS[a.config])
    name = a.config
    if a.config in ("nohistory", "allcat"):
        cfg["model"] = CONFIGS[a.base]["model"]
        name = f"{a.config}_{a.base}"
    w = no_memory(world()) if cfg.get("no_history") else world()
    convs, truth = load(a.split)
    if a.limit:
        convs = convs[: a.limit]
    out_dir = config.RUNS / "evals" / f"{name}-{a.split}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "results.jsonl"
    done = {json.loads(x)["id"]: json.loads(x) for x in out.read_text().splitlines()} if out.exists() else {}
    prev: dict[str, dict] = {}
    if a.rebuild and done:
        arch = config.RUNS / "evals" / "_archive" / a.rebuild / f"{name}-{a.split}"
        arch.mkdir(parents=True, exist_ok=True)
        (arch / "results.jsonl").write_text(out.read_text())
        prev, done = done, {}
        out.write_text("")
        print(f"archived {len(prev)} rows to {arch}", flush=True)
    retry = [k for k, r in done.items() if r.get("error")]
    if retry:  # API failures are not results: drop them so they run again
        done = {k: r for k, r in done.items() if not r.get("error")}
        out.write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in done.values()))
        print(f"{len(retry)} earlier API failures will be retried", flush=True)
    spent = sum(r.get("cost_usd", 0.0) for r in done.values())
    todo = [c for c in convs if c["id"] not in done]
    print(f"{name}-{a.split}: {len(todo)} to run, ${spent:.2f} spent so far", flush=True)
    ext = Claude(cfg["model"]) if cfg["model"] else None
    res = Claude(cfg.get("resolve_model") or cfg["model"]) if cfg["model"] else None

    stop = threading.Event()

    def one(c: dict) -> None:
        nonlocal spent
        with _lock:
            if spent >= a.budget or stop.is_set():
                return
        t0 = time.perf_counter()
        err = None
        try:
            if ext is None:
                d = parse_text(c["messages"], c["phone"], w)
                lines, intent, cost, extra = [dataclasses.asdict(x) for x in d.lines], d.intent, 0.0, {}
            else:
                r = parse_conversation(
                    c["messages"], c["phone"], ext, res, mode=cfg.get("mode", "retrieval"), w=w
                )
                lines, intent, cost = (
                    [dataclasses.asdict(x) for x in r.draft.lines],
                    r.draft.intent,
                    r.meter.cost_usd,
                )
                extra = {"extraction": r.extraction, "errors": r.errors, "holds": r.draft.holds, "llm_calls": r.meter.calls,
                         "llm_seconds": round(r.meter.seconds, 2), "cached": r.meter.cached}  # fmt: skip
        except (
            Exception
        ) as e:  # an API failure is recorded (and retried on the next run), never scored as a miss
            lines, intent, cost, extra, err = [], "error", 0.0, {}, f"{type(e).__name__}: {str(e)[:200]}"
            if "credit balance" in str(e) or "authentication" in str(e).lower():
                stop.set()  # no point burning through the queue
        s = score(truth[c["id"]], lines, intent, w)
        row = {"id": c["id"], "kind": c["kind"], "channel": c["channel"], "intent": intent, "score": s,
               "lines": [{**{k: ln[k] for k in ("sku", "qty", "unit", "qty_base", "confidence", "flags", "source", "unit_from")},
                          "features": (ln.get("evidence") or {}).get("features"), "why": (ln.get("evidence") or {}).get("why")} for ln in lines],
               "cost_usd": cost, "latency_s": round(time.perf_counter() - t0, 2), "error": err, **extra}  # fmt: skip
        old = prev.get(c["id"])
        if old and extra.get("cached") == extra.get(
            "llm_calls"
        ):  # nothing new was paid for: keep the first run's
            row.update(cost_usd=old.get("cost_usd", 0.0), latency_s=old.get("latency_s"), llm_seconds=old.get("llm_seconds"),
                       cached=old.get("cached", 0), rebuilt=True)  # fmt: skip
        with _lock:
            spent += cost
            with out.open("a") as f:
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        print(f"{c['id']} {c['kind']:9s} {c['channel']:5s} right {s['n_right']}/{s['n_truth']} pred {s['n_pred']} "
              f"exact={s['exact']} ${cost:.3f} {err or ''}", flush=True)  # fmt: skip

    with ThreadPoolExecutor(max_workers=1 if ext is None else a.workers) as ex:
        list(ex.map(one, todo))
    print(f"done; ${spent:.2f} total", flush=True)


if __name__ == "__main__":
    main()
