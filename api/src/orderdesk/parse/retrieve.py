"""Candidate SKUs for one mention: alias table + fuzzy matching + the customer's own history. Deterministic.

The model only ever chooses among these candidates, so retrieval recall is the ceiling on accuracy. The
eval reports it separately (recall@k), so a miss can be blamed on the right stage.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

from rapidfuzz import fuzz, process

from orderdesk.parse.normalize import norm, numbers
from orderdesk.parse.world import World

MAX_FAMILIES = 5


@dataclass
class Candidate:
    sku: str
    family: str
    family_score: float  # 0-100, best fuzzy match of the mention against the family's names
    alias_exact: bool  # a known name for the family appears verbatim in the mention
    in_history: bool  # the customer has ordered this exact SKU before
    family_in_history: bool
    size_match: bool  # a number in the mention's size text matches the SKU's size
    rank: int = 0
    score: float = 0.0


@cache
def _index(world: World) -> tuple[list[str], list[list[str]]]:
    terms: dict[str, set[str]] = {}
    for t, fams in world.aliases.items():
        terms.setdefault(norm(t), set()).update(fams)
    for s in world.skus.values():
        terms.setdefault(norm(world.family_name[s["family"]]), set()).add(s["family"])
    keys = sorted(terms)
    return keys, [sorted(terms[k]) for k in keys]


def _size_numbers(label: str) -> set[str]:
    out = set(numbers(label))
    for n in list(out):
        if "." in n:
            out.add(n.rstrip("0").rstrip("."))
    return out


def candidates(world: World, customer: dict | None, source: str, product: str, size: str | None,
               k_families: int = MAX_FAMILIES) -> list[Candidate]:  # fmt: skip
    keys, fams = _index(world)
    hist = world.usual(customer["id"]) if customer else {}
    hist_fams = {world.skus[s]["family"] for s in hist}
    queries = [
        q for q in dict.fromkeys((norm(product), norm(source))) if q
    ]  # ordered: runs must be reproducible
    fam_score: dict[str, float] = {}
    fam_exact: dict[str, bool] = {}
    for q in queries:
        padded = f" {q} "
        for term, score, i in process.extract(q, keys, scorer=fuzz.WRatio, limit=40):
            exact = len(term) >= 3 and f" {term} " in padded
            for f in fams[i]:
                s = float(score) + (10 if exact else 0)
                if s > fam_score.get(f, -1):
                    fam_score[f] = s
                fam_exact[f] = fam_exact.get(f, False) or exact
    for f in fam_score:
        if f in hist_fams:
            fam_score[f] += 8  # the customer's own products win ties
    top = sorted(fam_score, key=lambda f: (-fam_score[f], f))[
        :k_families
    ]  # ties broken by key, not hash order
    want = _size_numbers(size or "") | (set() if size else set(numbers(source)))
    out: list[Candidate] = []
    for f in top:
        for s in world.by_family[f]:
            have = _size_numbers(s["size_label"])
            out.append(
                Candidate(
                    sku=s["id"],
                    family=f,
                    family_score=round(fam_score[f], 1),
                    alias_exact=fam_exact.get(f, False),
                    in_history=s["id"] in hist,
                    family_in_history=f in hist_fams,
                    size_match=bool(want & have),
                )
            )
    for c in out:
        c.score = c.family_score + (6 if c.size_match else 0) + (5 if c.in_history else 0)
    out.sort(key=lambda c: (-c.score, c.sku))
    for i, c in enumerate(out):
        c.rank = i + 1
    return out


def all_skus(world: World, customer: dict | None) -> list[Candidate]:
    """The whole catalogue as candidates (the 'no retrieval' ablation)."""
    hist = world.usual(customer["id"]) if customer else {}
    hist_fams = {world.skus[s]["family"] for s in hist}
    return [
        Candidate(s["id"], s["family"], 0.0, False, s["id"] in hist, s["family"] in hist_fams, False, i + 1)
        for i, s in enumerate(world.skus.values())
    ]
