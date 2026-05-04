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
from exporters.mlb.cv import time_series_split, stats


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
        description="A/B isotonic vs logistic ML calibration via time-series k-fold CV",
    )
    parser.add_argument("--seasons", type=str, default="")
    parser.add_argument("--n-splits", type=int, default=5,
                        help="Number of time-series CV folds (default 5).")
    parser.add_argument("--output-dir", type=str, default=str(OUTPUT_DIR))
    args = parser.parse_args(argv)

    seasons = parse_seasons(args.seasons) or discover_seasons()
    if not seasons:
        print("No seasons with games.json found.")
        return 1

    print(f"\n=== Isotonic vs Logistic Calibration A/B (time-series k-fold) ===")
    print(f"  Seasons:    {seasons}")
    print(f"  Folds:      {args.n_splits}")
    print(f"  Method:     TimeSeriesSplit — train data is strictly before test\n")

    print("Running multi-season backtest to collect residuals...")
    pairs = capture_pairs_from_backtest(seasons)
    print(f"  Captured {len(pairs):,} (margin, won) pairs across {len(seasons)} seasons.\n")

    if len(pairs) < 100:
        print(f"Too few pairs ({len(pairs)}) to do a meaningful split.")
        return 1

    # Pairs come out of the backtest in chronological order (it walks
    # games sorted by date), so time_series_split's index ranges respect
    # no-look-ahead automatically.
    fold_results: list[dict] = []
    print(f"{'fold':>4s}  {'n_train':>7s}  {'n_test':>7s}  "
          f"{'naive':>7s}  {'logistic':>9s}  {'isotonic':>9s}  "
          f"{'delta':>8s}")
    print("  " + "-" * 60)
    for fold_i, (train_idx, test_idx) in enumerate(time_series_split(len(pairs), args.n_splits)):
        train = [pairs[i] for i in train_idx]
        test = [pairs[i] for i in test_idx]

        slope = _fit_logistic_slope(train)
        train_margins = [m for m, _ in train]
        train_outcomes = [y for _, y in train]
        fit = IsotonicRegressor.fit(train_margins, train_outcomes, increasing=True)

        test_margins = [m for m, _ in test]
        test_outcomes = [y for _, y in test]

        logistic_probs = [logistic_predict(m, slope) for m in test_margins]
        isotonic_probs = [isotonic_predict(m, fit) for m in test_margins]
        naive_probs = [0.5] * len(test_outcomes)

        b_naive = brier(naive_probs, test_outcomes)
        b_logistic = brier(logistic_probs, test_outcomes)
        b_isotonic = brier(isotonic_probs, test_outcomes)
        delta = b_logistic - b_isotonic

        print(f"  {fold_i:>4d}  {len(train):>7,d}  {len(test):>7,d}  "
              f"{b_naive:>7.4f}  {b_logistic:>9.4f}  {b_isotonic:>9.4f}  "
              f"{delta:>+8.4f}")

        fold_results.append({
            "fold": fold_i,
            "n_train": len(train),
            "n_test": len(test),
            "logistic_slope": slope,
            "isotonic_n_blocks": len(fit.blocks),
            "brier_naive": b_naive,
            "brier_logistic": b_logistic,
            "brier_isotonic": b_isotonic,
            "delta_logistic_minus_isotonic": delta,
        })

    # Aggregate — mean ± std + 95% normal-approx CI half-width.
    naive_stats = stats([f["brier_naive"] for f in fold_results])
    logistic_stats = stats([f["brier_logistic"] for f in fold_results])
    isotonic_stats = stats([f["brier_isotonic"] for f in fold_results])
    delta_stats = stats([f["delta_logistic_minus_isotonic"] for f in fold_results])

    print("\n--- Aggregate across folds (mean ± std) ---")
    print(f"  naive:    {naive_stats['mean']:.4f} ± {naive_stats['std']:.4f}")
    print(f"  logistic: {logistic_stats['mean']:.4f} ± {logistic_stats['std']:.4f}")
    print(f"  isotonic: {isotonic_stats['mean']:.4f} ± {isotonic_stats['std']:.4f}")
    print()
    print(f"  delta (log - iso): {delta_stats['mean']:+.4f} ± {delta_stats['std']:.4f}")
    print(f"  95% CI (normal approx): [{delta_stats['mean'] - delta_stats['ci_half']:+.4f}, "
          f"{delta_stats['mean'] + delta_stats['ci_half']:+.4f}]")
    print()

    # Honest verdict: only declare a winner if the CI doesn't cross zero.
    ci_lo = delta_stats['mean'] - delta_stats['ci_half']
    ci_hi = delta_stats['mean'] + delta_stats['ci_half']
    if ci_lo > 0:
        print("  → Isotonic BEATS logistic — CI excludes zero.")
    elif ci_hi < 0:
        print("  → Logistic BEATS isotonic — CI excludes zero.")
    else:
        print("  → Inconclusive — CI crosses zero. The apparent delta is")
        print("    within the across-fold variance and could be noise.")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"isotonic_compare_kfold_{datetime.utcnow().strftime('%Y-%m-%d')}.json"
    out_path.write_text(json.dumps({
        "as_of": datetime.utcnow().isoformat() + "Z",
        "method": "time_series_kfold",
        "seasons": seasons,
        "n_splits": args.n_splits,
        "n_pairs_total": len(pairs),
        "fold_results": fold_results,
        "aggregate": {
            "naive": naive_stats,
            "logistic": logistic_stats,
            "isotonic": isotonic_stats,
            "delta_logistic_minus_isotonic": delta_stats,
        },
    }, indent=2, default=str))
    print(f"\nWrote {out_path.relative_to(REPO_ROOT)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
