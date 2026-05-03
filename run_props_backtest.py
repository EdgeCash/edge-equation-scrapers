#!/usr/bin/env python3
"""
Edge Equation — MLB Player Props Backtest (offline, EXPERIMENTAL)
==================================================================
Walks every game in `data/backfill/mlb/<season>/` (games.json plus
boxscores.tar.gz) in chronological order. For each game, projects
what each starting player's prop probabilities WOULD have been
pre-game using only stats accumulated from prior games. Grades
projections against actual stat lines from the boxscore.

Strict no-look-ahead: per-player running totals are updated AFTER
each game's projections are graded.

Outputs to `data/experimental/props_backtests/props_<date>.json/csv`.
Sandboxed — never touches the website or daily card.

Per-season runtime: ~2-5 minutes (mostly JSON parse + per-game
projection). Per-season memory: ~190 MB (boxscores extracted from
tarball into memory).

Usage:
    # Default: all seasons in data/backfill/mlb/
    python run_props_backtest.py

    # Subset
    python run_props_backtest.py --seasons 2022,2023,2024
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

from exporters.mlb.props_backtest import PropsBacktestEngine


BACKFILL_DIR = REPO_ROOT / "data" / "backfill" / "mlb"
OUTPUT_DIR = REPO_ROOT / "data" / "experimental" / "props_backtests"


def discover_seasons() -> list[int]:
    if not BACKFILL_DIR.exists():
        return []
    out = []
    for child in BACKFILL_DIR.iterdir():
        if child.is_dir() and child.name.isdigit():
            if (child / "boxscores.tar.gz").exists():
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
        description="MLB player-props backtest (offline, EXPERIMENTAL)",
    )
    parser.add_argument(
        "--seasons", type=str, default="",
        help="Seasons to include (e.g. '2022,2023,2024' or '2022-2024'). "
             "Default: every season with boxscores on disk.",
    )
    parser.add_argument(
        "--output-dir", type=str, default=str(OUTPUT_DIR),
    )
    args = parser.parse_args(argv)

    seasons = parse_season_arg(args.seasons) or discover_seasons()
    if not seasons:
        print("No seasons with boxscores found. Run the MLB Backfill workflow")
        print("with --with-boxscores first.")
        return 1

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("\n=== MLB Player Props Backtest (EXPERIMENTAL) ===")
    print(f"Backfill dir: {BACKFILL_DIR}")
    print(f"Seasons:      {seasons}\n")

    engine = PropsBacktestEngine(BACKFILL_DIR)
    result = engine.run(seasons)

    overall = result["overall"]["overall"]
    print(f"\n--- Overall ({result['total_games_graded']:,} games graded, "
          f"{result['total_games_skipped']} skipped) ---")
    print(f"  bets:     {overall['n']:,}")
    print(f"  wins:     {overall['wins']:,}")
    print(f"  hit rate: {overall['hit_rate']}%")
    print(f"  units:    {overall['units_pl']:+.2f}")
    print(f"  ROI:      {overall['roi_pct']:+.2f}%")
    print(f"  Brier:    {overall['brier']}")

    print(f"\n--- Per-prop-type ---")
    print(f"{'prop_type':25s} {'n':>8s} {'hit%':>7s} {'units':>10s} {'ROI%':>7s} {'brier':>7s}")
    for row in result["overall"]["by_prop_type"]:
        brier = f"{row['brier']:.4f}" if row.get("brier") is not None else "—"
        print(
            f"{row['prop_type']:25s} {row['n']:>8,d} "
            f"{row['hit_rate']:>6.1f}% {row['units_pl']:>+9.2f} "
            f"{row['roi_pct']:>+6.2f}% {brier:>7s}"
        )

    if len(seasons) > 1:
        print(f"\n--- Per-season Brier (overall) ---")
        for season in seasons:
            ps = result["per_season"].get(season, {})
            psum = ps.get("summary", {}).get("overall", {})
            if psum:
                print(
                    f"  {season}: {psum['n']:>6,d} bets, "
                    f"hit {psum['hit_rate']}%, "
                    f"Brier {psum.get('brier')}"
                )

    date_tag = datetime.utcnow().strftime("%Y-%m-%d")
    seasons_tag = "-".join(str(s) for s in seasons)
    json_path = out_dir / f"props_{date_tag}_{seasons_tag}.json"
    json_path.write_text(json.dumps(result, indent=2, default=str))

    csv_path = out_dir / f"props_{date_tag}_{seasons_tag}.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "scope", "season", "prop_type", "n", "wins", "losses",
            "hit_rate", "units_pl", "roi_pct", "brier",
        ])
        w.writeheader()
        for row in result["overall"]["by_prop_type"]:
            w.writerow({"scope": "OVERALL", "season": "all", **row})
        for season in seasons:
            ps = result["per_season"].get(season, {})
            for row in ps.get("summary", {}).get("by_prop_type", []):
                w.writerow({"scope": "BY SEASON", "season": season, **row})

    print(f"\nWrote {json_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {csv_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
