"""Fit the per-line confidence model on the dev split (never test) and save it for the product.

    python -m evals.calibrate --config sonnet

Logistic regression with a small L2 penalty, fitted by Newton's method on dev-split predicted lines
(label: the line is exactly right). Writes data/model/confidence.json.
"""

from __future__ import annotations

import argparse
import json

import numpy as np

from orderdesk import config
from orderdesk.parse.confidence import FEATURES, WEIGHTS_PATH, featurize


def rows_xy(config_name: str, split: str) -> tuple[np.ndarray, np.ndarray]:
    path = config.RUNS / "evals" / f"{config_name}-{split}" / "results.jsonl"
    X, y = [], []
    for r in map(json.loads, path.read_text().splitlines()):
        right = r["score"]["pred_right"]
        for ln in r["lines"]:
            if not ln.get("sku") or ln["sku"] not in right:
                continue
            f = featurize({"features": ln.get("features") or {}}, ln["flags"])
            X.append([f[k] for k in FEATURES])
            y.append(float(right[ln["sku"]]))
    return np.array(X), np.array(y)


def fit(X: np.ndarray, y: np.ndarray, l2: float = 1.0, iters: int = 50) -> np.ndarray:
    Xb = np.hstack([np.ones((len(X), 1)), X])
    w = np.zeros(Xb.shape[1])
    reg = np.full(Xb.shape[1], l2)
    reg[0] = 0.0  # don't shrink the bias
    for _ in range(iters):
        p = 1 / (1 + np.exp(-Xb @ w))
        g = Xb.T @ (p - y) + reg * w
        H = (Xb * (p * (1 - p))[:, None]).T @ Xb + np.diag(reg)
        w -= np.linalg.solve(H, g)
    return w


def auc(p: np.ndarray, y: np.ndarray) -> float:
    pos, neg = p[y == 1], p[y == 0]
    if not len(pos) or not len(neg):
        return float("nan")
    return float((pos[:, None] > neg[None, :]).mean() + 0.5 * (pos[:, None] == neg[None, :]).mean())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="sonnet")
    a = ap.parse_args()
    X, y = rows_xy(a.config, "dev")
    w = fit(X, y)
    p = 1 / (1 + np.exp(-(np.hstack([np.ones((len(X), 1)), X]) @ w)))
    weights = {"bias": float(w[0]), **{k: float(v) for k, v in zip(FEATURES, w[1:], strict=True)}}
    WEIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    WEIGHTS_PATH.write_text(json.dumps({"fitted_on": f"{a.config}-dev", "lines": len(y), "accuracy": float(y.mean()),
                                        "dev_auc": round(auc(p, y), 4), "weights": weights}, indent=1) + "\n")  # fmt: skip
    print(f"fitted on {len(y)} dev lines ({y.mean():.1%} right); dev AUC {auc(p, y):.3f}")
    for k, v in weights.items():
        print(f"  {k:18s} {v:+.2f}")


if __name__ == "__main__":
    main()
