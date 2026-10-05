"""Per-line confidence: a small logistic model over evidence features, fitted on the dev split.

    p(line is right) = sigmoid(w · features + b)

Weights live in data/model/confidence.json, written by `python -m evals.calibrate` from dev-split results
(never the test split). Without that file, hand-set starting weights are used and the eval says so.
"""

from __future__ import annotations

import json
import math

from orderdesk import config
from orderdesk.parse.build import Draft

WEIGHTS_PATH = config.DATA / "model" / "confidence.json"
FEATURES = ["model_high", "model_medium", "alias_exact", "in_history", "family_in_history", "size_match",
            "size_given", "unit_given", "nickname", "from_image", "repeat", "top_rank", "unit_from_history"]  # fmt: skip
DEFAULT = {"bias": -1.0, "model_high": 2.0, "model_medium": 0.8, "alias_exact": 0.6, "in_history": 0.8,
           "family_in_history": 0.3, "size_match": 0.6, "size_given": 0.3, "unit_given": 0.4, "nickname": 0.5,
           "from_image": -0.5, "repeat": 1.5, "top_rank": 0.4, "unit_from_history": 0.0}  # fmt: skip


def featurize(ev: dict, flags: list[str]) -> dict[str, float]:
    f = ev.get("features") or {}
    model = f.get("model", ev.get("model_confidence", "low"))
    return {
        "model_high": float(model == "high"),
        "model_medium": float(model == "medium"),
        "alias_exact": float(bool(f.get("alias_exact"))),
        "in_history": float(bool(f.get("in_history"))),
        "family_in_history": float(bool(f.get("family_in_history"))),
        "size_match": float(bool(f.get("size_match"))),
        "size_given": float(bool(f.get("size_given"))),
        "unit_given": float(bool(f.get("unit_given"))),
        "nickname": float(bool(f.get("nickname"))),
        "from_image": float(bool(f.get("from_image"))),
        "repeat": float("from_last_order" in flags),
        "top_rank": float(f.get("rank", 99) == 1),
        "unit_from_history": float("unit_from_history" in flags),
    }


def load_weights() -> tuple[dict[str, float], str]:
    if WEIGHTS_PATH.exists():
        return json.loads(WEIGHTS_PATH.read_text())["weights"], "fitted"
    return DEFAULT, "default"


def probability(x: dict[str, float], w: dict[str, float]) -> float:
    z = w.get("bias", 0.0) + sum(w.get(k, 0.0) * v for k, v in x.items())
    return 1 / (1 + math.exp(-z))


def score_lines(draft: Draft) -> None:
    w, _ = load_weights()
    for ln in draft.lines:
        if ln.sku is None:
            ln.confidence = 0.0
            continue
        ln.confidence = round(probability(featurize(ln.evidence, ln.flags), w), 4)
