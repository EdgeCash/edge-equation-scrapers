#!/usr/bin/env python3
"""
Edge Equation — MLB Multi-Season Backfill (one-time bulk pull)
==============================================================
Pulls historical MLB game results and (optionally) per-game boxscores
across multiple seasons into `data/backfill/mlb/<season>/`. Used to
fuel offline model fine-tuning: extended-sample calibration refits,
multi-season Brier validation, prop backtest grading.

⚠️ Not a cron. Run manually when you want fresh historical data.
Idempotent — re-running skips already-cached games and boxscores.

Usage:
    # Fast: just game results for the last 4 completed seasons
    python run_mlb_backfill.py

    # Full: games + per-game boxscores for specified seasons (~45 min/season)
    python run_mlb_backfill.py --seasons 2022,2023,2024 --with-boxscores

    # Faster boxscore harvest (set request interval lower at your own risk;
    # default 1.0s is polite; 0.3s is fine for short bursts)
    python run_mlb_backfill.py --with-boxscores --request-interval 0.3

    # Custom output dir
    python run_mlb_backfill.py --output-dir /path/to/backfill
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scrapers.mlb.mlb_backfill_scraper import (
    MLBBackfillScraper, DEFAULT_REQUEST_INTERVAL_S,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "backfill" / "mlb"


def parse_seasons(spec: str) -> list[int]:
    """`2022,2023,2024` → [2022, 2023, 2024].
       `2022-2024`     → [2022, 2023, 2024]."""
    spec = spec.strip()
    if not spec:
        return []
    if "-" in spec and "," not in spec:
        start, end = spec.split("-", 1)
        return list(range(int(start), int(end) + 1))
    return [int(s.strip()) for s in spec.split(",") if s.strip()]


def default_seasons() -> list[int]:
    """The 4 most recent COMPLETED seasons. Avoids the in-progress year
    so we're not mixing live data with backfill."""
    current_year = datetime.utcnow().year
    return list(range(current_year - 4, current_year))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="MLB multi-season backfill (games + optional boxscores)",
    )
    parser.add_argument(
        "--seasons", type=str, default="",
        help="Seasons to fetch. e.g. '2022,2023,2024' or '2022-2024'. "
             "Default: the 4 most recent completed seasons.",
    )
    parser.add_argument(
        "--with-boxscores", action="store_true", default=False,
        help="Also fetch per-game boxscore (lineup + per-player stats). "
             "Heavy: ~2,500 calls per season at the default 1s interval "
             "(~42 minutes). Required for prop backtest grading.",
    )
    parser.add_argument(
        "--request-interval", type=float, default=DEFAULT_REQUEST_INTERVAL_S,
        help=f"Seconds between boxscore requests. "
             f"Default {DEFAULT_REQUEST_INTERVAL_S}.",
    )
    parser.add_argument(
        "--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR),
    )
    args = parser.parse_args(argv)

    seasons = parse_seasons(args.seasons) or default_seasons()

    print(f"\nMLB Backfill — seasons {seasons}")
    print(f"  Output dir: {args.output_dir}")
    print(f"  With boxscores: {args.with_boxscores}")
    if args.with_boxscores:
        per_season_min = int(2500 * args.request_interval / 60) + 1
        print(f"  Estimated time per season: ~{per_season_min} minutes")
    print()

    scraper = MLBBackfillScraper(
        output_root=Path(args.output_dir),
        request_interval_s=args.request_interval,
    )
    report = scraper.fetch_seasons(seasons, with_boxscores=args.with_boxscores)

    print("\n=== Summary ===")
    for season, stats in sorted(report.items()):
        print(
            f"  {season}: {stats['games']} games"
            + (
                f", boxscores +{stats['boxscores_fetched']} new "
                f"({stats['boxscores_skipped']} cached, "
                f"{stats['boxscores_failed']} failed)"
                if args.with_boxscores
                else ""
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
