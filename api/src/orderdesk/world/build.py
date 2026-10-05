"""Build the whole synthetic world and the eval sets. Deterministic.

    python -m orderdesk.world.build

Writes (product-visible):  data/world/{catalogue,customers,history,stock,aliases}.json
Writes (parser input):     data/eval/{dev,test,gold}/conversations.jsonl, data/eval/*/images/*.jpg
Writes (evals only):       data/eval/truth/{dev,test,gold}.jsonl, data/eval/truth/heldout_terms.json
And data/eval/manifest.json with counts and content hashes, so a silent change to the eval is visible.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

from orderdesk import config
from orderdesk.world.catalogue import FAMILIES, build_skus
from orderdesk.world.customers import add_nicknames, build_customers, build_history, build_stock
from orderdesk.world.images import render_list
from orderdesk.world.lexicon import GENERIC, split_terms
from orderdesk.world.messages import Renderer, Truth, TruthLine, base_qty, generate

SPLITS = {"dev": (120, 101, dt.datetime(2026, 10, 5, tzinfo=dt.UTC)), "test": (300, 202, dt.datetime(2026, 10, 12, tzinfo=dt.UTC))}  # fmt: skip
GOLD_SOURCE = config.TRUTH / "gold_source.jsonl"


def _dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n")


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def alias_table(skus) -> dict[str, list[str]]:
    """term -> family keys. Official names + seen street terms + generic group words. Never held-out terms."""
    seen, _ = split_terms()
    out: dict[str, set[str]] = {}
    for f in FAMILIES:
        for t in [f.name_en.lower(), f.name_ar, *seen[f.key]]:
            out.setdefault(t, set()).add(f.key)
    for t, fams in GENERIC.items():
        out.setdefault(t, set()).update(fams)
    return {t: sorted(v) for t, v in sorted(out.items())}


def build_gold(skus) -> tuple[list[dict], list[dict]]:
    """Hand-written conversations (not from the generator). Source lines name SKUs by family/size key."""
    if not GOLD_SOURCE.exists():
        return [], []
    by_key = {(s.family, s.size): s for s in skus}
    convs, truths = [], []
    for row in map(json.loads, GOLD_SOURCE.read_text().splitlines()):
        lines = []
        for fam, size, qty, unit in row["truth"]:
            s = by_key[(fam, size)]
            lines.append(
                asdict(
                    TruthLine(
                        s.id,
                        qty,
                        unit,
                        base_qty(s, qty, unit),
                        row["style"],
                        "(gold)",
                        False,
                        "gold",
                        True,
                        True,
                    )
                )
            )
        msgs = [
            {"id": f"wamid.{row['id']}.{i + 1}", "ts": row["ts"], "type": "text", "text": t}
            for i, t in enumerate(row["messages"])
        ]
        convs.append({"id": row["id"], "customer": row["customer"], "phone": row["phone"], "split": "gold", "kind": row["kind"], "channel": "text", "messages": msgs})  # fmt: skip
        truths.append({"id": row["id"], "customer": row["customer"], "kind": row["kind"], "lines": lines, "lead_style": row["style"]})  # fmt: skip
    return convs, truths


def main() -> None:
    rng = np.random.default_rng(config.SEED)
    skus = build_skus()
    customers = build_customers(skus, rng)
    add_nicknames(customers, {s.id: s for s in skus}, rng)
    history = build_history(customers, rng)
    stock = build_stock(skus, rng)
    world = config.WORLD
    _dump(world / "catalogue.json", [s.to_dict() for s in skus])
    _dump(world / "customers.json", [c.to_dict() for c in customers])
    _dump(world / "history.json", history)
    _dump(world / "stock.json", stock)
    _dump(world / "aliases.json", alias_table(skus))
    _, held = split_terms()
    _dump(config.TRUTH / "heldout_terms.json", held)

    fams = {f.key: f for f in FAMILIES}
    manifest: dict = {"built": "deterministic", "seed": config.SEED, "skus": len(skus), "customers": len(customers),
                      "history_orders": len(history), "splits": {}}  # fmt: skip
    for split, (n, seed, start) in SPLITS.items():
        r = Renderer(skus, fams, history, np.random.default_rng(seed))
        convs, truths = generate(r, customers, split, n, start)
        img_rng = np.random.default_rng(seed + 1)
        rows = []
        for c in convs:
            d = asdict(c)
            for m in d["messages"]:
                if m["type"] == "image":
                    rel = f"{split}/images/{c.id}.jpg"
                    crossed = None
                    if img_rng.random() < 0.25:  # a crossed-out line that must not be ordered
                        crossed = str(
                            img_rng.choice(
                                [
                                    "sugar 2 ctn",
                                    "pepsi 1 carton",
                                    "chips 2 box",
                                    "milk 5",
                                    "rice 1 bag",
                                    "tea 2 pkt",
                                ]
                            )
                        )
                    render_list(m.pop("lines"), crossed, img_rng, config.EVAL / rel)
                    m.pop("style", None)
                    m["image"] = rel
                    m["crossed_out"] = crossed is not None
            rows.append(d)
        # whether an image has a crossed-out line is eval metadata: it goes with the truth, not the input
        crossed_ids = set()
        for d in rows:
            for m in d["messages"]:
                if m.pop("crossed_out", False):
                    crossed_ids.add(d["id"])
        _jsonl(config.EVAL / split / "conversations.jsonl", rows)
        _jsonl(
            config.TRUTH / f"{split}.jsonl",
            [asdict(t) | {"crossed_out": t.id in crossed_ids} for t in truths],
        )
        manifest["splits"][split] = _summary(rows, truths)
    gconvs, gtruths = build_gold(skus)
    if gconvs:
        _jsonl(config.EVAL / "gold" / "conversations.jsonl", gconvs)
        _jsonl(config.TRUTH / "gold.jsonl", gtruths)
        manifest["splits"]["gold"] = _summary(
            gconvs, [Truth(**{**t, "lines": [TruthLine(**x) for x in t["lines"]]}) for t in gtruths]
        )
    manifest["hashes"] = {str(p.relative_to(config.DATA)): hashlib.sha256(p.read_bytes()).hexdigest()[:16]
                          for p in sorted(config.DATA.rglob("*.json*")) if "manifest" not in p.name}  # fmt: skip
    _dump(config.EVAL / "manifest.json", manifest)
    print(json.dumps({k: v for k, v in manifest.items() if k != "hashes"}, indent=1), file=sys.stderr)


def _summary(rows: list[dict], truths: list[Truth]) -> dict:
    lines = [ln for t in truths for ln in t.lines]
    return {
        "conversations": len(rows),
        "kinds": _count(t.kind for t in truths),
        "images": sum(1 for r in rows for m in r["messages"] if m["type"] == "image"),
        "lines": len(lines),
        "styles": _count(ln.style for ln in lines),
        "heldout_terms": sum(1 for ln in lines if not ln.term_seen and ln.via == "term"),
        "size_omitted": sum(1 for ln in lines if not ln.size_given and ln.via == "term"),
        "unit_omitted": sum(1 for ln in lines if not ln.unit_given and ln.via == "term"),
        "nicknames": sum(1 for ln in lines if ln.via == "nickname"),
    }


def _count(xs) -> dict:
    out: dict = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    return dict(sorted(out.items()))


if __name__ == "__main__":
    main()
