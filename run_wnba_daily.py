#!/usr/bin/env python3
"""
Edge Equation — WNBA Daily Update
=================================
Fetches games for a single date (default: yesterday in ET) and
merges them into the appropriate season's games.json. Idempotent.

WNBA season starts mid-May and runs through October. The daily cron
fires year-round; on no-game days the runner reports 0 games and
nothing commits.

Usage:
    python run_wnba_daily.py
    python run_wnba_daily.py --date 2025-08-15
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scrapers.wnba.wnba_backfill_scraper import WNBABackfillScraper


DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "backfill" / "wnba"


def yesterday_et() -> str:
    et = datetime.now(timezone(timedelta(hours=-5)))
    return (et.date() - timedelta(days=1)).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="WNBA daily game-results update",
    )
    parser.add_argument("--date", type=str, default="")
    parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args(argv)

    target_date = args.date or yesterday_et()

    print(f"\nWNBA Daily Update — {target_date}")
    print(f"  Output dir: {args.output_dir}\n")

    scraper = WNBABackfillScraper(output_root=Path(args.output_dir))
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
