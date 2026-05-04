#!/usr/bin/env python3
"""
Edge Equation — Isotonic vs Logistic Calibration A/B
====================================================
A focused offline experiment: does isotonic regression produce a
better-calibrated win probability than the linear logistic slope
we currently fit in BacktestEngine?

The current calibration is `_fit_logistic_slope()` — a single-parameter
sigmoid `p = 1/(1+exp(-slope * margin))`. That handles uniform
miscalibration but can't fix non-linear distortions (e.g. "model is
well-calibrated at moderate probabilities but overconfident at the
extremes").

Isotonic regression is the textbook fix: a monotonic, piecewise-linear
fit that can correct any monotonic miscalibration without overfitting.

Methodology:
1. Run the multi-season backtest end-to-end. Capture the (proj_margin,
   won 0/1) pairs the engine collects internally.
2. Random 80/20 train/test split (deterministic seed for reproducibility).
3. Fit BOTH methods on TRAIN.
4. Apply each method to TEST margins to produce calibrated probabilities.
5. Score each method's calibrated probabilities by Brier score on TEST.
6. Report the delta. Smaller Brier = better calibration.

Output: stdout summary + written JSON at
data/experimental/isotonic_compare/<date>.json.

Usage:
    python run_isotonic_compare.py
    python run_isotonic_compare.py --seasons 2022,2023,2024,2025
    python run_isotonic_compare.py --train-frac 0.8 --seed 42
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import exporters.mlb.backtest as bt_module
from exporters.mlb.backtest import BacktestEngine, _fit_logistic_slope
from exporters.mlb.isotonic import IsotonicRegressor


BACKFILL_DIR = REPO_ROOT / "data" / "backfill" / "mlb"
OUTPUT_DIR = REPO_ROOT / "data" / "experimental" / "isotonic_compare"


def parse_seasons(spec: str) -> list[int]:
    spec = spec.strip()
    if not spec:
        return []
    if "-" in spec and "," not in spec:
        start, end = spec.split("-", 1)
        return list(range(int(start), int(end) + 1))
    return [int(s.strip()) for s in spec.split(",") if s.strip()]


def discover_seasons() -> list[int]:
    if not BACKFILL_DIR.exists():
        return []
    out = []
    for child in BACKFILL_DIR.iterdir():
        if child.is_dir() and child.name.isdigit():
            if (child / "games.json").exists():
                out.append(int(child.name))
    return sorted(out)


def capture_pairs_from_backtest(seasons: list[int]) -> list[tuple[float, int]]:
    """Run BacktestEngine.run() while monkey-patching _calibration to
    capture the residual ml_pairs before they're aggregated. Returns the
    raw (proj_margin, won) pairs from every game in the multi-season
    walk."""
    captured: dict = {}
    original = bt_module.BacktestEngine._calibration

    def capturing(residuals: dict) -> dict:
        captured["ml_pairs"] = list(residuals.get("ml_pairs", []))
        return original(residuals)

    bt_module.BacktestEngine._calibration = staticmethod(capturing)
    try:
        engine = BacktestEngine.from_multi_season(BACKFILL_DIR, seasons)
        engine.run()
    finally:
        bt_module.BacktestEngine._calibration = staticmethod(original)

    return captured.get("ml_pairs", [])


def split_pairs(
    pairs: list[tuple[float, int]],
    train_frac: float,
    seed: int,
) -> tuple[list[tuple[float, int]], list[tuple[float, int]]]:
    rng = random.Random(seed)
    shuffled = list(pairs)
    rng.shuffle(shuffled)
    cut = int(len(shuffled) * train_frac)
    return shuffled[:cut], shuffled[cut:]


def logistic_predict(margin: float, slope: float) -> float:
    """Apply the ML logistic-slope calibration to a projected margin."""
    xc = max(-30.0, min(30.0, slope * margin))
    return 1.0 / (1.0 + math.exp(-xc))


def isotonic_predict(margin: float, fit) -> float:
    """Apply the isotonic fit to a projected margin. Returns probability
    in [0, 1]."""
    val = float(IsotonicRegressor.predict(fit, margin))
    return max(0.0, min(1.0, val))


def brier(predictions: list[float], outcomes: list[int]) -> float:
    """Mean squared difference between predicted probabilities and 0/1
    outcomes. Lower is better."""
    if not predictions:
        return 0.0
    return sum((p - y) ** 2 for p, y in zip(predictions, outcomes)) / len(predictions)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="A/B isotonic vs logistic ML calibration",
    )
    parser.add_argument("--seasons", type=str, default="")
    parser.add_argument("--train-frac", type=float, default=0.8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", type=str, default=str(OUTPUT_DIR))
    args = parser.parse_args(argv)

    seasons = parse_seasons(args.seasons) or discover_seasons()
    if not seasons:
        print("No seasons with games.json found.")
        return 1

    print(f"\n=== Isotonic vs Logistic Calibration A/B ===")
    print(f"  Seasons:    {seasons}")
    print(f"  Train frac: {args.train_frac}")
    print(f"  Seed:       {args.seed}\n")

    print("Running multi-season backtest to collect residuals...")
    pairs = capture_pairs_from_backtest(seasons)
    print(f"  Captured {len(pairs):,} (margin, won) pairs across {len(seasons)} seasons.\n")

    if len(pairs) < 100:
        print(f"Too few pairs ({len(pairs)}) to do a meaningful split.")
        return 1

    train, test = split_pairs(pairs, args.train_frac, args.seed)
    print(f"  Train: {len(train):,} pairs")
    print(f"  Test:  {len(test):,} pairs\n")

    # Fit both methods on TRAIN.
    print("Fitting logistic slope on TRAIN...")
    slope = _fit_logistic_slope(train)
    print(f"  win_prob_slope = {slope:.4f}")

    print("Fitting isotonic on TRAIN...")
    train_margins = [m for m, _ in train]
    train_outcomes = [y for _, y in train]
    fit = IsotonicRegressor.fit(train_margins, train_outcomes, increasing=True)
    print(f"  isotonic blocks = {len(fit.blocks)}")

    # Apply each method to TEST margins.
    test_margins = [m for m, _ in test]
    test_outcomes = [y for _, y in test]

    logistic_probs = [logistic_predict(m, slope) for m in test_margins]
    isotonic_probs = [isotonic_predict(m, fit) for m in test_margins]
    naive_probs = [0.5] * len(test)  # constant 0.5 baseline

    brier_logistic = brier(logistic_probs, test_outcomes)
    brier_isotonic = brier(isotonic_probs, test_outcomes)
    brier_naive = brier(naive_probs, test_outcomes)

    print("\n--- Brier scores on TEST (lower = better) ---")
    print(f"  naive (constant 0.5): {brier_naive:.4f}")
    print(f"  logistic slope:       {brier_logistic:.4f}")
    print(f"  isotonic:             {brier_isotonic:.4f}")

    delta = brier_logistic - brier_isotonic
    pct = (delta / brier_logistic * 100) if brier_logistic > 0 else 0.0
    print(f"\n  delta (log - iso):    {delta:+.4f}  ({pct:+.2f}% relative)")
    if delta > 0:
        print("  → Isotonic WINS on this test split.")
    elif delta < 0:
        print("  → Logistic WINS on this test split.")
    else:
        print("  → Tie.")

    # Diagnostic: look at calibration quality at different margin slices.
    print("\n--- Reliability table on TEST (binned by predicted prob) ---")
    print(f"  {'bin':>10s}  {'n':>5s}  {'avg_pred_log':>13s}  {'avg_pred_iso':>13s}  {'actual':>8s}")
    bins = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]
    for lo, hi in bins:
        # Use logistic predictions to bin (so both methods see the same buckets)
        idxs = [i for i, p in enumerate(logistic_probs) if lo <= p < hi]
        if not idxs:
            continue
        n = len(idxs)
        avg_log = sum(logistic_probs[i] for i in idxs) / n
        avg_iso = sum(isotonic_probs[i] for i in idxs) / n
        actual = sum(test_outcomes[i] for i in idxs) / n
        print(f"  [{lo:.1f}-{hi:.1f}]  {n:>5d}  {avg_log:>13.4f}  {avg_iso:>13.4f}  {actual:>8.4f}")

    # Persist the result for the experimental record.
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"isotonic_compare_{datetime.utcnow().strftime('%Y-%m-%d')}.json"
    out_path.write_text(json.dumps({
        "as_of": datetime.utcnow().isoformat() + "Z",
        "seasons": seasons,
        "train_frac": args.train_frac,
        "seed": args.seed,
        "n_train": len(train),
        "n_test": len(test),
        "logistic_slope": slope,
        "isotonic_n_blocks": len(fit.blocks),
        "brier_naive": brier_naive,
        "brier_logistic": brier_logistic,
        "brier_isotonic": brier_isotonic,
        "delta_logistic_minus_isotonic": delta,
        "pct_relative_improvement": pct,
    }, indent=2, default=str))
    print(f"\nWrote {out_path.relative_to(REPO_ROOT)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
