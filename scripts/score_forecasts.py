"""Score resolved forecasts and fit the recalibration used for new forecasts.

Outputs:
  scores/summary.md          headline scores, by forecaster, kind and thesis; calibration table
  scores/recalibration.json  {k, b, n, fitted_at, active}: new system forecasts are mapped
                             p -> sigmoid(k * logit(p) + b) once n >= MIN_N
Brier score: mean of (p - outcome)^2. 0.25 = always saying 50%. Lower is better.
"""
from __future__ import annotations

import datetime as dt
import json
import math
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "forecasts" / "forecasts.yaml"
OUT = ROOT / "scores"
MIN_N = 20          # resolved forecasts needed before recalibration switches on
BINS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]


def brier(pairs: list[tuple[float, int]]) -> float:
    return sum((p - o) ** 2 for p, o in pairs) / len(pairs)


def logit(p: float) -> float:
    p = min(max(p, 0.01), 0.99)
    return math.log(p / (1 - p))


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def calibrate(p: float, k: float, b: float) -> float:
    return sigmoid(k * logit(p) + b)


def fit(pairs: list[tuple[float, int]]) -> tuple[float, float]:
    """Grid search for k (sharpen/soften) and b (bias), lightly penalised towards k=1, b=0."""
    best = (1.0, 0.0, float("inf"))
    for ki in range(30, 161, 5):
        k = ki / 100
        for bi in range(-60, 61, 5):
            b = bi / 100
            loss = brier([(calibrate(p, k, b), o) for p, o in pairs]) + 0.002 * ((k - 1) ** 2 + b ** 2)
            if loss < best[2]:
                best = (k, b, loss)
    return best[0], best[1]


def effective_p(f: dict) -> float:
    return float(f["probability"])


def main() -> None:
    doc = yaml.safe_load(REGISTRY.read_text())
    fc = doc["forecasts"]
    resolved = [f for f in fc if f.get("status") == "resolved" and f.get("outcome") in (0, 1)]
    open_ = [f for f in fc if f.get("status") == "open"]
    OUT.mkdir(exist_ok=True)
    lines = [f"# Forecast scores, {dt.date.today().isoformat()}", "",
             f"{len(resolved)} resolved, {len(open_)} open, {len(fc)} in total.", ""]
    if resolved:
        pairs = [(effective_p(f), int(f["outcome"])) for f in resolved]
        lines += [f"Brier score, system forecasts: **{brier(pairs):.3f}** (0.25 = always 50%; lower is better).", ""]
        overrides = [(float(f["override"]["probability"]), int(f["outcome"])) for f in resolved if f.get("override")]
        if overrides:
            same = [(effective_p(f), int(f["outcome"])) for f in resolved if f.get("override")]
            lines += [f"Your overrides: Brier {brier(overrides):.3f} vs system {brier(same):.3f} on the same {len(overrides)} forecasts.", ""]
        groups: dict[str, list] = defaultdict(list)
        for f in resolved:
            groups[f"kind: {f.get('kind', 'thesis')}"].append((effective_p(f), int(f["outcome"])))
            groups[f"thesis: {f.get('thesis', 'none')}"].append((effective_p(f), int(f["outcome"])))
        lines += ["| Group | n | Brier |", "| --- | --- | --- |"]
        lines += [f"| {g} | {len(v)} | {brier(v):.3f} |" for g, v in sorted(groups.items())]
        lines += ["", "## Calibration", "", "| Stated probability | n | Mean stated | Share that happened |", "| --- | --- | --- | --- |"]
        for lo, hi in BINS:
            b = [(p, o) for p, o in pairs if lo <= p < hi]
            if b:
                lines.append(f"| {lo:.0%}–{min(hi, 1):.0%} | {len(b)} | {sum(p for p, _ in b) / len(b):.0%} | {sum(o for _, o in b) / len(b):.0%} |")
        k, b0 = fit(pairs) if len(pairs) >= MIN_N else (1.0, 0.0)
    else:
        k, b0 = 1.0, 0.0
        lines.append("No forecasts resolved yet.")
    active = len(resolved) >= MIN_N
    rec = {"k": k, "b": b0, "n": len(resolved), "min_n": MIN_N, "active": active,
           "fitted_at": dt.date.today().isoformat(),
           "rule": "new system forecasts: p_final = sigmoid(k * logit(p_raw) + b); record both"}
    (OUT / "recalibration.json").write_text(json.dumps(rec, indent=2) + "\n")
    lines += ["", "## Recalibration", "",
              (f"Active: k = {k:.2f}, b = {b0:.2f}, fitted on {len(resolved)} forecasts." if active
               else f"Not active yet: needs {MIN_N} resolved forecasts, has {len(resolved)}.")]
    (OUT / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
