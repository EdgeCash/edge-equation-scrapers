#!/usr/bin/env python3
"""
Edge Equation — NHL Daily Update
================================
Fetches games for a single date (default: yesterday in ET) and
merges them into the appropriate season's games.json. Idempotent —
re-runs are safe and replace in-progress entries with their FINAL
versions.

Designed to run on a daily cron AFTER game results have settled.
NHL playoff games can finish in the early-AM ET hours; we run at
13:00 UTC (8 AM ET) to be safe.

Usage:
    python run_nhl_daily.py                      # yesterday in ET
    python run_nhl_daily.py --date 2025-04-15    # specific date
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scrapers.nhl.nhl_backfill_scraper import NHLBackfillScraper


DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "backfill" / "nhl"


def yesterday_et() -> str:
    """Yesterday's date in US Eastern Time. We don't import zoneinfo
    just for this — UTC-4 / UTC-5 works fine since we're rounding to
    a day anyway."""
    et = datetime.now(timezone(timedelta(hours=-5)))
    return (et.date() - timedelta(days=1)).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="NHL daily game-results update",
    )
    parser.add_argument(
        "--date", type=str, default="",
        help="YYYY-MM-DD. Default: yesterday in ET.",
    )
    parser.add_argument(
        "--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR),
    )
    args = parser.parse_args(argv)

    target_date = args.date or yesterday_et()

    print(f"\nNHL Daily Update — {target_date}")
    print(f"  Output dir: {args.output_dir}\n")

    scraper = NHLBackfillScraper(output_root=Path(args.output_dir))
    report = scraper.update_for_date(target_date)

    print("\n=== Summary ===")
    print(f"  Season:           {report['season']}")
    print(f"  Date harvested:   {report['target_date']}")
    print(f"  Fetched:          {report['fetched']} games")
    print(f"  New (added):      {report['added']}")
    print(f"  Updated existing: {report['updated']}")
    print(f"  Total in season:  {report['total_in_season']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
