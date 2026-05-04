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
    parser = argparse.ArgumentParser(description="A/B Elo vs current-model ML calibration")
    parser.add_argument("--seasons", type=str, default="")
    parser.add_argument("--warmup-games", type=int, default=500,
                        help="Skip first N games when scoring ELO (cold-start ratings).")
    parser.add_argument("--train-frac", type=float, default=0.8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", type=str, default=str(OUTPUT_DIR))
    args = parser.parse_args(argv)

    seasons = parse_seasons(args.seasons) or discover_seasons()
    if not seasons:
        print("No seasons with games.json found.")
        return 1

    print("\n=== ELO vs Current-Model A/B ===")
    print(f"  Seasons:        {seasons}")
    print(f"  Warmup games:   {args.warmup_games}")
    print(f"  Train frac:     {args.train_frac}")
    print(f"  Seed:           {args.seed}\n")

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

    rng = random.Random(args.seed)
    indices = list(range(n_match))
    rng.shuffle(indices)
    cut = int(n_match * args.train_frac)
    train_idx = set(indices[:cut])
    test_idx = [i for i in range(n_match) if i not in train_idx]

    train_pairs = [(aligned[i]["margin_proj"], aligned[i]["actual_home_won"])
                    for i in train_idx]
    slope = _fit_logistic_slope(train_pairs)
    print(f"Logistic slope (fit on {len(train_pairs):,} train pairs): {slope:.4f}")

    elo_probs = [aligned[i]["elo_prob_home"] for i in test_idx]
    outcomes = [aligned[i]["actual_home_won"] for i in test_idx]
    logistic_probs = [
        logistic_predict(aligned[i]["margin_proj"], slope) for i in test_idx
    ]
    naive_probs = [0.5] * len(test_idx)
    print(f"  evaluating both methods on {len(test_idx):,} TEST games "
          f"(same games for both methods — true head-to-head)\n")

    brier_naive = brier(naive_probs, outcomes)
    brier_logistic = brier(logistic_probs, outcomes)
    brier_elo = brier(elo_probs, outcomes)

    print("--- Brier scores on TEST (lower = better) ---")
    print(f"  naive (constant 0.5):   {brier_naive:.4f}")
    print(f"  current model (logistic): {brier_logistic:.4f}")
    print(f"  ELO-only:               {brier_elo:.4f}")

    # 50/50 ensemble
    ensemble = [(p1 + p2) / 2 for p1, p2 in zip(elo_probs, logistic_probs)]
    brier_ensemble = brier(ensemble, outcomes)
    print(f"  50/50 ensemble:         {brier_ensemble:.4f}")

    delta_vs_logistic = brier_logistic - brier_elo
    pct = (delta_vs_logistic / brier_logistic * 100) if brier_logistic > 0 else 0.0
    print(f"\n  delta (logistic - elo): {delta_vs_logistic:+.4f}  ({pct:+.2f}% relative)")
    if delta_vs_logistic > 0:
        print("  → ELO BEATS current model on this test split.")
    elif delta_vs_logistic < 0:
        print("  → Current model BEATS ELO on this test split.")
    else:
        print("  → Tie.")

    delta_ensemble = brier_logistic - brier_ensemble
    if delta_ensemble > 0:
        print(f"  ensemble delta vs logistic: {delta_ensemble:+.4f} → ensemble helps.")
    else:
        print(f"  ensemble delta vs logistic: {delta_ensemble:+.4f} → ensemble doesn't help.")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"elo_compare_{datetime.utcnow().strftime('%Y-%m-%d')}.json"
    out_path.write_text(json.dumps({
        "as_of": datetime.utcnow().isoformat() + "Z",
        "seasons": seasons,
        "warmup_games": args.warmup_games,
        "train_frac": args.train_frac,
        "seed": args.seed,
        "n_total_elo_games": len(elo_by_pk),
        "n_logistic_pairs": len(logistic_pairs),
        "n_matched": n_match,
        "n_train": len(train_idx),
        "n_test": len(test_idx),
        "logistic_slope": slope,
        "brier_naive": brier_naive,
        "brier_logistic": brier_logistic,
        "brier_elo": brier_elo,
        "brier_ensemble": brier_ensemble,
        "delta_logistic_minus_elo": delta_vs_logistic,
        "pct_relative": pct,
    }, indent=2, default=str))
    print(f"\nWrote {out_path.relative_to(REPO_ROOT)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
