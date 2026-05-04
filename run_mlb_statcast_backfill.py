#!/usr/bin/env python3
"""
Edge Equation — MLB Statcast Expected-Stats Backfill (one-shot, ~1 min)
=======================================================================
Per-season xBA / xSLG / xwOBA leaderboards from Baseball Savant. The
single biggest free improvement to a player-prop projection model:
expected stats correlate ~30% better with NEXT-year actual outcomes
than this-year actual stats.

⚠️ Not a cron. Idempotent — already-completed seasons are skipped.

Usage:
    python run_mlb_statcast_backfill.py
    python run_mlb_statcast_backfill.py --seasons 2022,2023,2024
    python run_mlb_statcast_backfill.py --seasons 2022-2025
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scrapers.mlb.mlb_statcast_scraper import (
    MLBStatcastScraper, DEFAULT_REQUEST_INTERVAL_S,
    DEFAULT_BATTER_MIN, DEFAULT_PITCHER_MIN,
)


BACKFILL_DIR = REPO_ROOT / "data" / "backfill" / "mlb"


def parse_seasons(spec: str) -> list[int]:
    spec = spec.strip()
    if not spec:
        return []
    if "-" in spec and "," not in spec:
        start, end = spec.split("-", 1)
        return list(range(int(start), int(end) + 1))
    return [int(s.strip()) for s in spec.split(",") if s.strip()]


def default_seasons() -> list[int]:
    """Every season already on disk (we only have meaningful Statcast
    coverage where the boxscore tarball already lives)."""
    if not BACKFILL_DIR.exists():
        return []
    out = []
    for child in BACKFILL_DIR.iterdir():
        if child.is_dir() and child.name.isdigit():
            out.append(int(child.name))
    return sorted(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="MLB Statcast xBA / xSLG / xwOBA backfill",
    )
    parser.add_argument(
        "--seasons", type=str, default="",
        help="Seasons. e.g. '2022,2023,2024' or '2022-2024'. "
             "Default: every season already on disk.",
    )
    parser.add_argument(
        "--request-interval", type=float, default=DEFAULT_REQUEST_INTERVAL_S,
        help=f"Seconds between API calls. Default {DEFAULT_REQUEST_INTERVAL_S}.",
    )
    parser.add_argument(
        "--batter-min", type=int, default=DEFAULT_BATTER_MIN,
        help=f"Minimum batter PAs to include. Default {DEFAULT_BATTER_MIN}.",
    )
    parser.add_argument(
        "--pitcher-min", type=int, default=DEFAULT_PITCHER_MIN,
        help=f"Minimum pitcher batters-faced to include. Default {DEFAULT_PITCHER_MIN}.",
    )
    parser.add_argument(
        "--backfill-dir", type=str, default=str(BACKFILL_DIR),
    )
    args = parser.parse_args(argv)

    seasons = parse_seasons(args.seasons) or default_seasons()
    if not seasons:
        print("No seasons found on disk. Run the MLB Backfill workflow first.")
        return 1

    print("\n=== MLB Statcast Expected-Stats Backfill ===")
    print(f"  Backfill dir:     {args.backfill_dir}")
    print(f"  Seasons:          {seasons}")
    print(f"  Request interval: {args.request_interval}s")
    print(f"  Batter min PAs:   {args.batter_min}")
    print(f"  Pitcher min BFs:  {args.pitcher_min}\n")

    scraper = MLBStatcastScraper(
        backfill_root=Path(args.backfill_dir),
        request_interval_s=args.request_interval,
        batter_min=args.batter_min,
        pitcher_min=args.pitcher_min,
    )
    report = scraper.fetch_seasons(seasons)

    print("\n=== Summary ===")
    for season in seasons:
        meta = report.get(season, {})
        if meta.get("skipped"):
            print(f"  {season}: already complete; skipped.")
        elif meta.get("error"):
            print(f"  {season}: ERROR — {meta['error']}")
        else:
            print(
                f"  {season}: batters={meta.get('n_batters', 0)}, "
                f"pitchers={meta.get('n_pitchers', 0)}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
