# ADR 0004: Confidence is fitted on dev; touchless thresholds are measured on test

**Status:** accepted · **Phase:** P3

## Context
The pitch to the distributor is "the desk confirms most lines without reading them". That claim needs a line-level probability of being right and a threshold below which a person looks. Model self-reports ("high/medium/low") are not calibrated. A threshold chosen on the same data it is reported on overstates the touchless rate.

## Decision
- Each draft line records its features: model certainty, exact alias hit, in the customer's history, size given and matched, unit from history, came from a photo, nickname, repeat order, top retrieval rank.
- `evals.calibrate` fits a logistic model on the **dev** split (Sonnet run) and writes `data/model/confidence.json`. The app reads it whenever it scores lines; without it the hand-set defaults apply.
- `evals.report` recomputes confidence for every **test** line from the stored features and the fitted weights. It then reports AUC and the touchless rate at 1%, 2% and 3% line error among the lines nobody checks, and per whole order at a few thresholds.

## Consequences
- The touchless numbers in `docs/results/eval.md` are out-of-sample. The same split and the same weights could set the production threshold, but only after shadow mode on real messages ([rollout plan](../engagement/rollout-plan.md)): synthetic dev data is not the customer's data.
- The weights are a 14-number JSON file, readable in a code review. A feature with a surprising sign (for example `family_in_history` comes out negative; the likely reason is that a familiar family in the wrong size is a common trap) is visible and explainable.
- Refitting is one command after any change to retrieval or prompts. The eval runner's cache makes re-running dev cheap when prompts haven't changed.
