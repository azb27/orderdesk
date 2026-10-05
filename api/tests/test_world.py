"""The synthetic world and eval sets are internally consistent, deterministic, and keep held-out names hidden."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import asdict

import numpy as np
import pytest

from orderdesk import config
from orderdesk.world.catalogue import FAMILIES, build_skus, ean13
from orderdesk.world.customers import add_nicknames, build_customers, build_history
from orderdesk.world.lexicon import split_terms
from orderdesk.world.messages import Renderer, generate

CAT = {s["id"]: s for s in json.loads((config.WORLD / "catalogue.json").read_text())}
ALIASES = json.loads((config.WORLD / "aliases.json").read_text())


def _truth(split: str) -> list[dict]:
    return [json.loads(x) for x in (config.TRUTH / f"{split}.jsonl").read_text().splitlines()]


def _convs(split: str) -> list[dict]:
    return [json.loads(x) for x in (config.EVAL / split / "conversations.jsonl").read_text().splitlines()]


def test_barcodes_are_valid_ean13():
    for s in build_skus():
        d = [int(c) for c in s.barcode]
        assert len(d) == 13 and (sum(x * (3 if i % 2 else 1) for i, x in enumerate(d[:12])) + d[12]) % 10 == 0
    assert ean13("a") != ean13("b")


@pytest.mark.parametrize("split", ["dev", "test", "gold"])
def test_truth_matches_catalogue_and_conversations(split):
    truths, convs = _truth(split), _convs(split)
    assert [t["id"] for t in truths] == [c["id"] for c in convs]
    for t in truths:
        for ln in t["lines"]:
            s = CAT[ln["sku"]]
            mult = {"carton": s["carton_size"], "pack": s["pack_size"] or 1, "piece": 1}[ln["unit"]]
            assert ln["qty_base"] == ln["qty"] * mult > 0
        assert len({ln["sku"] for ln in t["lines"]}) == len(t["lines"]), "a SKU appears once per order"
        if t["kind"] == "not_order":
            assert t["lines"] == []


def test_heldout_terms_never_reach_the_alias_table():
    _, held = split_terms()
    for fam, terms in held.items():
        for t in terms:
            assert fam not in ALIASES.get(t, []), (fam, t)
    assert sum(map(len, held.values())) > 200


def test_parser_inputs_carry_no_truth():
    for split in ("dev", "test", "gold"):
        text = (config.EVAL / split / "conversations.jsonl").read_text()
        for leak in ("qty_base", "SL-1", "term_seen", "crossed_out"):
            assert leak not in text, (split, leak)


def test_images_exist_for_image_messages():
    for split in ("dev", "test"):
        for c in _convs(split):
            for m in c["messages"]:
                if m["type"] == "image":
                    assert (config.EVAL / m["image"]).stat().st_size > 10_000


def test_generator_is_deterministic():
    def run():
        rng = np.random.default_rng(config.SEED)
        skus = build_skus()
        cs = build_customers(skus, rng)
        add_nicknames(cs, {s.id: s for s in skus}, rng)
        h = build_history(cs, rng)
        r = Renderer(skus, {f.key: f for f in FAMILIES}, h, np.random.default_rng(5))
        convs, truths = generate(r, cs, "t", 15, dt.datetime(2026, 10, 1, tzinfo=dt.UTC))
        return [asdict(c) for c in convs], [asdict(t) for t in truths]

    assert run() == run()


def test_committed_eval_matches_the_generator():
    """Rebuilding must reproduce the committed test split exactly (manifest hash)."""
    manifest = json.loads((config.EVAL / "manifest.json").read_text())
    for rel, h in manifest["hashes"].items():
        assert hashlib.sha256((config.DATA / rel).read_bytes()).hexdigest()[:16] == h, rel
