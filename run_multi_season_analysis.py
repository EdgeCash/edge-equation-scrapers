#!/usr/bin/env python3
"""
Edge Equation — Multi-Season MLB Backtest Analysis (offline)
============================================================
Loads every season available in `data/backfill/mlb/` (plus optionally
the current season's live backfill) and runs the full BacktestEngine
across the combined dataset. Reports per-market hit rate, ROI, Brier,
and the calibration constants fitted from the larger sample.

Designed to surface exactly what the multi-season backfill is telling
us about model performance — does our edge hold up across years, or
was it noise on a single sample?

Outputs land in `data/experimental/multi_season_backtests/` (sandboxed,
not on the website).

Usage:
    # Default: all seasons in data/backfill/mlb/
    python run_multi_season_analysis.py

    # Specific seasons
    python run_multi_season_analysis.py --seasons 2022,2023,2024

    # Include current-season live data (pulls fresh from API)
    python run_multi_season_analysis.py --include-current
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from exporters.mlb.backtest import BacktestEngine
from scrapers.mlb.mlb_game_scraper import MLBGameScraper


BACKFILL_DIR = REPO_ROOT / "data" / "backfill" / "mlb"
OUTPUT_DIR = REPO_ROOT / "data" / "experimental" / "multi_season_backtests"


def discover_seasons() -> list[int]:
    """Return sorted list of seasons that have games.json on disk."""
    if not BACKFILL_DIR.exists():
        return []
    out = []
    for child in BACKFILL_DIR.iterdir():
        if child.is_dir() and child.name.isdigit():
            if (child / "games.json").exists():
                out.append(int(child.name))
    return sorted(out)


def parse_season_arg(spec: str) -> list[int]:
    spec = spec.strip()
    if not spec:
        return []
    if "-" in spec and "," not in spec:
        start, end = spec.split("-", 1)
        return list(range(int(start), int(end) + 1))
    return [int(s.strip()) for s in spec.split(",") if s.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Multi-season MLB backtest (offline analysis)",
    )
    parser.add_argument(
        "--seasons", type=str, default="",
        help="Seasons to include (e.g. '2022,2023,2024' or '2022-2024'). "
             "Default: every season with backfill data on disk.",
    )
    parser.add_argument(
        "--include-current", action="store_true", default=False,
        help="Also include the current season's live backfill (pulls "
             "fresh data via the API). Slower but reflects the latest data.",
    )
    parser.add_argument(
        "--output-dir", type=str, default=str(OUTPUT_DIR),
    )
    args = parser.parse_args(argv)

    seasons = parse_season_arg(args.seasons) or discover_seasons()
    if not seasons:
        print("No backfill seasons found. Run the MLB Backfill workflow first.")
        return 1

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("\n=== Multi-Season MLB Backtest ===")
    print(f"Backfill dir: {BACKFILL_DIR}")
    print(f"Seasons:      {seasons}")

    current_games = None
    if args.include_current:
        print("\nFetching current-season live backfill...")
        scraper = MLBGameScraper()
        current_year = datetime.utcnow().year
        end = (datetime.utcnow().date()).isoformat()
        current_games = scraper.fetch_schedule(f"{current_year}-03-20", end)
        print(f"  +{len(current_games)} current-season games")

    print("\nLoading historical games...")
    engine = BacktestEngine.from_multi_season(
        backfill_dir=BACKFILL_DIR,
        seasons=seasons,
        current_season_games=current_games,
    )
    loaded = getattr(engine, "_seasons_loaded", {})
    for s, n in sorted(loaded.items(), key=lambda kv: str(kv[0])):
        print(f"  {s}: {n:,} games")
    print(f"Total: {len(engine.games):,} games")

    print("\nRunning backtest...")
    result = engine.run()
    overall = result["overall"]
    print(
        f"  Overall: {overall['bets']:,} bets, "
        f"hit rate {overall['hit_rate']:.1f}%, "
        f"units {overall['units_pl']:+.2f}, "
        f"ROI {overall['roi_pct']:+.2f}%, "
        f"Brier {overall.get('brier'):.4f}"
    )

    print("\nPer market:")
    print(f"{'market':14s} {'bets':>7s} {'hit%':>7s} {'units':>10s} {'ROI%':>7s} {'brier':>7s}")
    for row in result["summary_by_bet_type"]:
        brier = f"{row['brier']:.4f}" if row.get("brier") is not None else "—"
        print(
            f"{row['bet_type']:14s} {row['bets']:>7d} "
            f"{row['hit_rate']:>6.1f}% {row['units_pl']:>+9.2f} "
            f"{row['roi_pct']:>+6.2f}% {brier:>7s}"
        )

    print(f"\nCalibrated constants (fit from {result['calibration']['n_residuals']:,} residuals):")
    cal = result["calibration"]
    for k in ("total_sd", "team_total_sd", "margin_sd", "f5_total_sd",
              "f5_margin_sd", "win_prob_slope"):
        print(f"  {k:18s} {cal.get(k)}")

    # Persist to data/experimental/multi_season_backtests/
    date_tag = datetime.utcnow().strftime("%Y-%m-%d")
    seasons_tag = "-".join(str(s) for s in sorted(loaded.keys() if loaded else seasons)
                           if isinstance(s, int))
    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "seasons": list(loaded.keys()) if loaded else seasons,
        "n_games": len(engine.games),
        "overall": overall,
        "summary_by_bet_type": result["summary_by_bet_type"],
        "calibration": cal,
        "daily_pl_sample": result["daily_pl"][-30:],  # last 30 days only
    }
    json_path = out_dir / f"multi_season_{date_tag}_{seasons_tag}.json"
    json_path.write_text(json.dumps(payload, indent=2, default=str))

    csv_path = out_dir / f"multi_season_{date_tag}_{seasons_tag}.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "scope", "bet_type", "bets", "wins", "losses", "pushes",
            "hit_rate", "units_pl", "roi_pct", "brier",
        ])
        w.writeheader()
        w.writerow({"scope": "OVERALL", "bet_type": "all", **overall})
        for row in result["summary_by_bet_type"]:
            w.writerow({"scope": "BY TYPE", **row})

    print(f"\nWrote {json_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {csv_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
