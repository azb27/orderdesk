"""The parser's deterministic steps, and the model steps with a scripted fake (no API calls)."""

from __future__ import annotations

import json
import os
import subprocess
import sys

from orderdesk import config
from orderdesk.parse.build import Resolved, build_draft, unusual_qty
from orderdesk.parse.fuzzy import parse_text
from orderdesk.parse.llm import Scripted
from orderdesk.parse.normalize import norm
from orderdesk.parse.pipeline import parse_conversation, validate_extraction
from orderdesk.parse.retrieve import candidates
from orderdesk.parse.world import world

W = world()
C = W.customers["C1002"]


def _sku(family: str, size: str) -> str:
    return next(s["id"] for s in W.by_family[family] if s["size"] == size)


def _ext(*lines, intent="order"):
    return {"intent": intent, "lines": [dict(message=0, source=s, product=p, size=z, quantity=q, unit=u, action=a)
                                        for s, p, z, q, u, a in lines]}  # fmt: skip


# ---- normalisation and retrieval ----------------------------------------------------------------------
def test_norm_unifies_arabic_and_digits():
    assert norm("كرتونة  ٣") == "كرتونه 3"
    assert norm("أرز") == norm("ارز")
    assert norm("Pepsi, 2 CTN!") == "pepsi 2 ctn"


def test_retrieval_finds_the_family_for_common_names():
    for source, product, size, family in [
        ("santra soda 330", "orange soda", "330", "mirage_orange"),
        ("amrood juice", "guava juice", None, "sunfield_guava"),
        ("tel 1.8 litre", "sunflower oil", "1.8 litre", "sunola_sunflower"),
        ("لبن قليل الدسم ١ لتر", "low fat laban", "1 لتر", "barari_laban_low"),
    ]:
        fams = {c.family for c in candidates(W, C, source, product, size)}
        assert family in fams, (source, fams)


def test_retrieval_boosts_the_customers_own_items():
    usual = next(iter(W.usual(C["id"])))
    fam = W.skus[usual]["family"]
    cands = candidates(W, C, W.family_name[fam], W.family_name[fam], None)
    assert any(c.in_history for c in cands[:6])


# ---- the order builder ------------------------------------------------------------------------------------
def test_units_convert_in_code_and_default_from_history():
    sku, u = next(iter(W.usual(C["id"]).items()))
    d = build_draft(W, C, "order", [Resolved(sku, 2, None, "add", "x")])
    ln = d.lines[0]
    assert ln.unit == u.unit and ln.unit_from == "history" and "unit_from_history" in ln.flags
    assert ln.qty_base == W.base_qty(sku, 2, u.unit)
    assert ln.amount_fils == ln.qty_base * W.price_fils(C, sku)


def test_invalid_unit_falls_back_and_is_flagged():
    sku = _sku("royale_basmati", "20")  # sold one bag at a time: no packs
    d = build_draft(W, None, "order", [Resolved(sku, 2, "pack", "add", "x")])
    assert d.lines[0].unit == "piece" and "unit_guessed" in d.lines[0].flags and "needs_review" in d.holds


def test_repeat_last_order_then_remove_add_and_set():
    last = W.last_order(C["id"])
    first, second = last["lines"][0]["sku"], last["lines"][-1]["sku"]
    new = _sku("klenzo_bleach", "1000")
    d = build_draft(W, C, "repeat_last_order", [
        Resolved(first, 1, None, "remove", "no x"),
        Resolved(new, 2, "carton", "add", "add bleach"),
        Resolved(second, 7, "piece", "set", "make it 7"),
    ], repeat_last=True)  # fmt: skip
    got = {ln.sku: ln for ln in d.lines}
    assert first not in got and got[new].qty == 2 and got[second].qty == 7 and got[second].unit == "piece"
    assert len(got) == len(last["lines"]) + (0 if new in {x["sku"] for x in last["lines"]} else 1) - 1


def test_credit_hold_and_out_of_stock():
    over = next(c for c in W.customers.values() if c["balance_fils"] > c["credit_limit_fils"])
    d = build_draft(W, over, "order", [Resolved(_sku("al_wadi", "500p"), 1, "carton", "add", "x")])
    assert "credit_hold" in d.holds
    oos = next(s for s, n in W.stock.items() if n == 0)
    d = build_draft(W, C, "order", [Resolved(oos, 1, "piece", "add", "x")])
    assert "out_of_stock" in d.lines[0].flags and "needs_review" in d.holds
    assert all(W.stock[s] > 0 for s in d.lines[0].substitutes)


def test_unresolved_and_bad_quantities_never_become_order_lines():
    d = build_draft(
        W,
        C,
        "order",
        [
            Resolved(None, 2, "carton", "add", "mystery"),
            Resolved(_sku("al_wadi", "500p"), 2.5, "carton", "add", "x"),
        ],
    )
    assert all(ln.qty_base == 0 for ln in d.lines) and d.total_fils == 0
    assert {f for ln in d.lines for f in ln.flags} == {"unresolved", "bad_quantity"}


# ---- model steps (scripted) ---------------------------------------------------------------------------------
def test_a_choice_outside_the_candidates_is_rejected_not_repaired():
    ext = _ext(("santra soda 330 2 peti", "orange soda", "330", 2, "carton", "add"))
    fake = Scripted([{"choices": [{"line": 0, "sku": "SL-99999", "confidence": "high", "why": "made up"}]}])
    r = parse_conversation(
        [{"type": "text", "text": "santra soda 330 2 peti"}], C["phone"], Scripted([ext]), fake
    )
    assert r.draft.lines[0].sku is None and any("not a candidate" in e for e in r.errors)


def test_happy_path_uses_only_offered_ids_and_code_does_the_arithmetic():
    ext = _ext(("santra soda 330 2 peti", "orange soda", "330", 2, "carton", "add"))
    want = _sku("mirage_orange", "330c")
    fake = Scripted([{"choices": [{"line": 0, "sku": want, "confidence": "high", "why": "santra = orange"}]}])
    r = parse_conversation(
        [{"type": "text", "text": "santra soda 330 2 peti"}], C["phone"], Scripted([ext]), fake
    )
    ln = r.draft.lines[0]
    assert ln.sku == want and ln.qty_base == 2 * W.skus[want]["carton_size"] and 0 < ln.confidence < 1
    tool = fake.requests[0]["tool"]["input_schema"]["properties"]["choices"]["items"]["properties"]["sku"][
        "enum"
    ]
    assert want in tool and "NONE" in tool


def test_not_order_makes_no_lines_and_skips_the_second_call():
    fake = Scripted([])
    r = parse_conversation([{"type": "text", "text": "driver kab aayega?"}], C["phone"],
                           Scripted([{"intent": "not_order", "lines": [], "question": "delivery time"}]), fake)  # fmt: skip
    assert r.draft.lines == [] and fake.requests == []


def test_extraction_validation_rejects_bad_fields():
    x, errs = validate_extraction({"intent": "order", "lines": [
        {"message": 9, "source": "a", "product": "cola", "size": None, "quantity": -1, "unit": "crate", "action": "add"},
        {"message": 0, "source": "b", "product": "", "size": None, "quantity": 1, "unit": None, "action": "add"},
    ]}, n_messages=1)  # fmt: skip
    assert len(x["lines"]) == 1 and x["lines"][0]["quantity"] is None and x["lines"][0]["unit"] is None
    assert x["lines"][0]["message"] == 0 and len(errs) == 3


def test_prompts_never_contain_ground_truth():
    convs = [json.loads(x) for x in (config.EVAL / "dev" / "conversations.jsonl").read_text().splitlines()]
    c = next(x for x in convs if x["channel"] == "image")
    ext = Scripted([{"intent": "order", "lines": []}])
    parse_conversation(c["messages"], c["phone"], ext, Scripted([]))
    blob = json.dumps(ext.requests[0]["content"])
    assert '"type": "image"' in blob and "SL-" not in blob and "qty_base" not in blob


# ---- the fallback parser ----------------------------------------------------------------------------------------
def test_fuzzy_fallback_reads_plain_lines_and_flags_everything():
    d = parse_text(
        [{"type": "text", "text": "al wadi water 500 ml 3 ctn\nsunflower oil 1.8 l 6 pcs"}], C["phone"]
    )
    got = {ln.sku: ln for ln in d.lines}
    assert _sku("al_wadi", "500p") in got and got[_sku("al_wadi", "500p")].qty == 3
    assert _sku("sunola_sunflower", "1800") in got and got[_sku("sunola_sunflower", "1800")].unit == "piece"
    assert "needs_review" in d.holds and all(ln.confidence == 0 for ln in d.lines)


def test_retrieval_is_identical_across_processes():
    """Tie-breaking must not depend on hash order, or prompts (and the response cache) differ run to run."""
    code = ("from orderdesk.parse.world import world; from orderdesk.parse.retrieve import candidates; w=world(); "
            "print([c.sku for c in candidates(w, w.customers['C1002'], 'water 2 ctn', 'water', None)])")  # fmt: skip
    outs = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**os.environ,
            "PYTHONHASHSEED": str(seed)}).stdout for seed in (1, 2, 3)}  # fmt: skip
    assert len(outs) == 1 and "SL-" in outs.pop()


def test_quantities_far_outside_history_are_flagged_for_a_look():
    w = world()
    cust = w.customers["C1004"]
    most, _ = w.largest("C1004")
    sku = max(most, key=lambda k: most[k])
    s = w.skus[sku]
    assert not unusual_qty(w, "C1004", sku, most[sku])  # what they have ordered before is fine
    assert unusual_qty(w, "C1004", sku, 3 * most[sku] + 1)  # "450 g" read as 450 cartons is not
    cartons = 3 * most[sku] // s["carton_size"] + 1
    d = build_draft(w, cust, "order", [Resolved(sku, cartons, "carton", "add", "x")])
    assert "unusual_qty" in d.lines[0].flags and "needs_review" in d.holds
    never = next(k for k in w.skus if k not in most)  # never ordered: judged against their largest order
    assert not unusual_qty(w, "C1004", never, 1)
    assert unusual_qty(w, "C1004", never, 10**6)


def test_no_size_written_and_one_usual_size_takes_their_size():
    usual = W.usual(C["id"])
    fam, mine = next(
        (f, ks[0])
        for f in W.by_family
        if len(ks := [k for k in usual if W.skus[k]["family"] == f]) == 1 and len(W.by_family[f]) > 1
    )
    other = next(s["id"] for s in W.by_family[fam] if s["id"] != mine)
    text = W.family_name[fam].lower()
    ext = _ext((f"{text} 2 ctn", text, None, 2, "carton", "add"))
    fake = Scripted([{"choices": [{"line": 0, "sku": other, "confidence": "low", "why": "guessed a size"}]}])
    r = parse_conversation([{"type": "text", "text": f"{text} 2 ctn"}], C["phone"], Scripted([ext]), fake)
    ln = r.draft.lines[0]
    assert ln.sku == mine and "size_from_history" in ln.flags
    # a written size is never overridden
    ext2 = _ext((f"{text} 2 ctn", text, W.skus[other]["size_label"], 2, "carton", "add"))
    fake2 = Scripted([{"choices": [{"line": 0, "sku": other, "confidence": "high", "why": "size written"}]}])
    r2 = parse_conversation([{"type": "text", "text": f"{text} 2 ctn"}], C["phone"], Scripted([ext2]), fake2)
    assert r2.draft.lines[0].sku == other


def test_removing_a_size_they_did_not_order_last_time_removes_the_one_they_did():
    last = W.last_order(C["id"])
    target = next(
        ln["sku"]
        for ln in last["lines"]
        if len(W.by_family[W.skus[ln["sku"]]["family"]]) > 1
        and sum(W.skus[x["sku"]]["family"] == W.skus[ln["sku"]]["family"] for x in last["lines"]) == 1
    )
    sibling = next(s["id"] for s in W.by_family[W.skus[target]["family"]] if s["id"] != target)
    d = build_draft(
        W, C, "repeat_last_order", [Resolved(sibling, None, None, "remove", "no x")], repeat_last=True
    )
    assert target not in {ln.sku for ln in d.lines} and any("Removed" in n for n in d.notes)
