#!/usr/bin/env python3
"""
Edge Equation — ELO vs Current-Model Calibration A/B
====================================================
Does a simple Elo rating system (just team-vs-team game results,
nothing else) produce a better-calibrated ML probability than our
current ProjectionModel + logistic-slope pipeline?

Methodology:
1. Walk multi-season MLB backfill chronologically.
2. For each game G (after a warm-up period), compute ELO win prob
   using ratings as of BEFORE G (no look-ahead). Record
   (elo_prob, actual_outcome).
3. Update ratings with G's result.
4. Capture the same (margin_proj, actual) pairs the BacktestEngine
   uses, fit its logistic slope on a TRAIN split, evaluate on TEST.
5. Compare Brier scores on the TEST games.

Output: stdout summary + JSON written to
data/experimental/elo_compare/<date>.json.

Important caveat: ELO knows ONLY the schedule of wins/losses. Our
current model knows starting pitchers, bullpen factors, splits,
xstats, weather, lineup. If ELO matches or beats the current model,
that's a sign the per-team aggregates are doing most of the work
and the SP/BP/etc. signals are mostly noise. If the current model
clearly beats ELO, that confirms the per-game features are pulling
their weight beyond just "this team is good."

Usage:
    python run_elo_compare.py
    python run_elo_compare.py --seasons 2022,2023,2024,2025
    python run_elo_compare.py --warmup-games 500 --train-frac 0.8
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
from exporters.mlb.cv import time_series_split, stats
from exporters.mlb.elo import (
    EloCalculator, GameResult, EloRatings, DEFAULT_RATING, LEAGUE_PARAMS,
)


BACKFILL_DIR = REPO_ROOT / "data" / "backfill" / "mlb"
OUTPUT_DIR = REPO_ROOT / "data" / "experimental" / "elo_compare"


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


def walk_games_for_elo(seasons: list[int]) -> dict[int, dict]:
    """Walk every game chronologically, computing ELO pre-game win
    probability for each. Returns a dict keyed by game_pk with
    {elo_prob_home, actual_home_won, home_games_before,
    away_games_before, date} so the caller can match against a
    separate prediction stream (e.g. backtest ml_pairs) by game_pk
    without worrying about iteration-order mismatches.

    Sort key matches the backtest's `sorted(games, key=g['date'])`
    so the chronological order is identical — important because ELO
    ratings depend on the order of update.
    """
    all_games: list[dict] = []
    for season in seasons:
        path = BACKFILL_DIR / str(season) / "games.json"
        if not path.exists():
            continue
        all_games.extend(json.loads(path.read_text()))

    # Match BacktestEngine sort key exactly: sorted(games, key=date).
    all_games.sort(key=lambda g: g.get("date", ""))

    ratings: dict[str, "Decimal"] = {}
    games_played: dict[str, int] = {}
    params = LEAGUE_PARAMS["mlb"]
    k, hfa = params["k"], params["hfa"]

    out: dict[int, dict] = {}
    for g in all_games:
        home = g.get("home_team")
        away = g.get("away_team")
        pk = g.get("game_pk")
        if (not home or not away or pk is None
                or g.get("home_score") is None
                or g.get("away_score") is None):
            continue

        # ELO pre-game probability using ratings BEFORE this game.
        home_r = ratings.get(home, DEFAULT_RATING)
        away_r = ratings.get(away, DEFAULT_RATING)
        snapshot = EloRatings(league="mlb", ratings=ratings, games=games_played)
        elo_prob = float(EloCalculator.win_probability("mlb", home, away, snapshot))

        actual_home_won = 1 if g["home_score"] > g["away_score"] else 0
        out[pk] = {
            "date": g.get("date"),
            "season": g.get("season"),
            "home": home,
            "away": away,
            "home_score": g["home_score"],
            "away_score": g["away_score"],
            "elo_prob_home": elo_prob,
            "actual_home_won": actual_home_won,
            "home_games_before": games_played.get(home, 0),
            "away_games_before": games_played.get(away, 0),
        }

        # Update ratings AFTER prediction (no look-ahead).
        new_h, new_a = EloCalculator.update(
            home_r, away_r, g["home_score"], g["away_score"], k, hfa,
        )
        ratings[home] = new_h
        ratings[away] = new_a
        games_played[home] = games_played.get(home, 0) + 1
        games_played[away] = games_played.get(away, 0) + 1

    return out


def capture_logistic_predictions(
    seasons: list[int],
) -> tuple[list[tuple[float, int]], list[int]]:
    """Replay the backtest, capturing both ml_pairs and the parallel
    ml_pair_pks list so callers can match by game_pk.

    Returns (pairs, pks) where pks[i] is the game_pk of pairs[i].
    """
    captured: dict = {}
    original = bt_module.BacktestEngine._calibration

    def capturing(residuals: dict) -> dict:
        captured["ml_pairs"] = list(residuals.get("ml_pairs", []))
        captured["ml_pair_pks"] = list(residuals.get("ml_pair_pks", []))
        return original(residuals)

    bt_module.BacktestEngine._calibration = staticmethod(capturing)
    try:
        engine = BacktestEngine.from_multi_season(BACKFILL_DIR, seasons)
        engine.run()
    finally:
        bt_module.BacktestEngine._calibration = staticmethod(original)
    return captured.get("ml_pairs", []), captured.get("ml_pair_pks", [])


def logistic_predict(margin: float, slope: float) -> float:
    xc = max(-30.0, min(30.0, slope * margin))
    return 1.0 / (1.0 + math.exp(-xc))


def brier(predictions: list[float], outcomes: list[int]) -> float:
    if not predictions:
        return 0.0
    return sum((p - y) ** 2 for p, y in zip(predictions, outcomes)) / len(predictions)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="A/B Elo vs current-model ML calibration via time-series k-fold CV",
    )
    parser.add_argument("--seasons", type=str, default="")
    parser.add_argument("--warmup-games", type=int, default=500,
                        help="Skip first N games when scoring ELO (cold-start ratings).")
    parser.add_argument("--n-splits", type=int, default=5,
                        help="Number of time-series CV folds (default 5).")
    parser.add_argument("--output-dir", type=str, default=str(OUTPUT_DIR))
    args = parser.parse_args(argv)

    seasons = parse_seasons(args.seasons) or discover_seasons()
    if not seasons:
        print("No seasons with games.json found.")
        return 1

    print("\n=== ELO vs Current-Model A/B (time-series k-fold) ===")
    print(f"  Seasons:        {seasons}")
    print(f"  Warmup games:   {args.warmup_games}")
    print(f"  Folds:          {args.n_splits}")
    print(f"  Method:         TimeSeriesSplit — train data is strictly before test\n")

    print("Walking games chronologically with ELO replay...")
    elo_by_pk = walk_games_for_elo(seasons)
    print(f"  {len(elo_by_pk):,} games with ELO predictions\n")

    print("Replaying backtest to capture current-model (margin_proj, won) pairs...")
    logistic_pairs, logistic_pks = capture_logistic_predictions(seasons)
    print(f"  {len(logistic_pairs):,} logistic pairs captured (with game_pks)\n")

    # Match streams by game_pk. Build aligned arrays where every entry
    # corresponds to the SAME game in both ELO and current-model views.
    aligned: list[dict] = []
    for pair, pk in zip(logistic_pairs, logistic_pks):
        elo_rec = elo_by_pk.get(pk)
        if elo_rec is None:
            continue
        # Skip warmup games (rating unstable). Game qualifies once
        # both teams have played at least warmup_games / (~2 games/team)
        # — using the larger team's count as the threshold.
        max_games_before = max(
            elo_rec["home_games_before"], elo_rec["away_games_before"],
        )
        if max_games_before < args.warmup_games / 30:  # ~30 teams in MLB
            continue
        # Sanity: the home team (elo perspective) is the team in the
        # backtest's residual whose perspective we use. The backtest
        # uses (margin_proj = home_runs - away_runs, won = home_won 0/1).
        # If actual_home_won doesn't match pair[1], something's wrong.
        if pair[1] != elo_rec["actual_home_won"]:
            # Should be impossible — both derived from the same final
            # scores. If we hit this, the matching is broken.
            continue
        aligned.append({
            "game_pk": pk,
            "margin_proj": pair[0],
            "actual_home_won": pair[1],
            "elo_prob_home": elo_rec["elo_prob_home"],
            "date": elo_rec["date"],
        })

    n_match = len(aligned)
    print(f"  {n_match:,} games matched between streams "
          f"(after warmup + {len(logistic_pairs) - n_match:,} unmatched)\n")
    if n_match < 100:
        print("Too few matched games to compare meaningfully.")
        return 1

    # Sort aligned by date so time_series_split's index ranges respect
    # no-look-ahead. Both source streams should already be chronological,
    # but we sort defensively in case backfill order ever changes.
    aligned.sort(key=lambda r: (r.get("date") or "", r["game_pk"]))

    fold_results: list[dict] = []
    print(f"{'fold':>4s}  {'n_train':>7s}  {'n_test':>7s}  "
          f"{'logistic':>9s}  {'elo':>7s}  {'ensemble':>9s}  "
          f"{'log-elo':>9s}")
    print("  " + "-" * 65)
    for fold_i, (train_idx, test_idx) in enumerate(
        time_series_split(n_match, args.n_splits)
    ):
        train_pairs = [(aligned[i]["margin_proj"], aligned[i]["actual_home_won"])
                        for i in train_idx]
        slope = _fit_logistic_slope(train_pairs)

        elo_probs = [aligned[i]["elo_prob_home"] for i in test_idx]
        outcomes = [aligned[i]["actual_home_won"] for i in test_idx]
        logistic_probs = [
            logistic_predict(aligned[i]["margin_proj"], slope) for i in test_idx
        ]
        ensemble_probs = [(p1 + p2) / 2 for p1, p2 in zip(elo_probs, logistic_probs)]

        b_logistic = brier(logistic_probs, outcomes)
        b_elo = brier(elo_probs, outcomes)
        b_ensemble = brier(ensemble_probs, outcomes)
        delta_log_elo = b_logistic - b_elo

        print(f"  {fold_i:>4d}  {len(train_idx):>7,d}  {len(test_idx):>7,d}  "
              f"{b_logistic:>9.4f}  {b_elo:>7.4f}  {b_ensemble:>9.4f}  "
              f"{delta_log_elo:>+9.4f}")

        fold_results.append({
            "fold": fold_i,
            "n_train": len(train_idx),
            "n_test": len(test_idx),
            "logistic_slope": slope,
            "brier_logistic": b_logistic,
            "brier_elo": b_elo,
            "brier_ensemble": b_ensemble,
            "delta_logistic_minus_elo": delta_log_elo,
        })

    logistic_stats = stats([f["brier_logistic"] for f in fold_results])
    elo_stats = stats([f["brier_elo"] for f in fold_results])
    ensemble_stats = stats([f["brier_ensemble"] for f in fold_results])
    delta_stats = stats([f["delta_logistic_minus_elo"] for f in fold_results])

    print("\n--- Aggregate across folds (mean ± std) ---")
    print(f"  current model:  {logistic_stats['mean']:.4f} ± {logistic_stats['std']:.4f}")
    print(f"  ELO-only:       {elo_stats['mean']:.4f} ± {elo_stats['std']:.4f}")
    print(f"  50/50 ensemble: {ensemble_stats['mean']:.4f} ± {ensemble_stats['std']:.4f}")
    print()
    print(f"  delta (logistic - elo): {delta_stats['mean']:+.4f} ± {delta_stats['std']:.4f}")
    print(f"  95% CI (normal approx): [{delta_stats['mean'] - delta_stats['ci_half']:+.4f}, "
          f"{delta_stats['mean'] + delta_stats['ci_half']:+.4f}]")
    print()

    ci_lo = delta_stats['mean'] - delta_stats['ci_half']
    ci_hi = delta_stats['mean'] + delta_stats['ci_half']
    if ci_lo > 0:
        print("  → ELO BEATS current model — CI excludes zero.")
    elif ci_hi < 0:
        print("  → Current model BEATS ELO — CI excludes zero.")
    else:
        print("  → Inconclusive — CI crosses zero. Apparent delta is")
        print("    within the across-fold variance and could be noise.")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"elo_compare_kfold_{datetime.utcnow().strftime('%Y-%m-%d')}.json"
    out_path.write_text(json.dumps({
        "as_of": datetime.utcnow().isoformat() + "Z",
        "method": "time_series_kfold",
        "seasons": seasons,
        "n_splits": args.n_splits,
        "warmup_games": args.warmup_games,
        "n_total_elo_games": len(elo_by_pk),
        "n_logistic_pairs": len(logistic_pairs),
        "n_matched": n_match,
        "fold_results": fold_results,
        "aggregate": {
            "logistic": logistic_stats,
            "elo": elo_stats,
            "ensemble": ensemble_stats,
            "delta_logistic_minus_elo": delta_stats,
        },
    }, indent=2, default=str))
    print(f"\nWrote {out_path.relative_to(REPO_ROOT)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
