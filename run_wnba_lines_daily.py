#!/usr/bin/env python3
"""
Edge Equation — WNBA Daily Lines Snapshot
=========================================
Pulls one LIVE snapshot from The Odds API and merges it into the
current season's lines.json. WNBA seasons are calendar-year, so
season routing is simply `d.year`.

Costs 1 credit per call.

Usage:
    ODDS_API_KEY=... python run_wnba_lines_daily.py
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scrapers.odds_api.odds_api_backfill_scraper import OddsApiBackfillScraper
from scrapers.odds_api.team_mappings import WNBA_TEAM_NAMES

SPORT_KEY = "basketball_wnba"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "backfill" / "wnba"
DEFAULT_QUOTA_LOG = REPO_ROOT / "public" / "data" / "wnba" / "quota_log.json"


def _season_for_date(d: date) -> int:
    """WNBA seasons are calendar-year (mid-May through October)."""
    return d.year


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WNBA daily lines snapshot")
    parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--quota-log", type=str, default=str(DEFAULT_QUOTA_LOG))
    args = parser.parse_args(argv)

    api_key = os.environ.get("ODDS_API_KEY", "").strip()
    if not api_key:
        print("ERROR: ODDS_API_KEY env var is required.", file=sys.stderr)
        return 2

    print("\nWNBA Daily Lines Snapshot")
    scraper = OddsApiBackfillScraper(
        sport_key=SPORT_KEY,
        team_name_to_code=WNBA_TEAM_NAMES,
        output_root=Path(args.output_dir),
        api_key=api_key,
        quota_log_path=Path(args.quota_log),
    )
    report = scraper.snapshot_today(season_for_date=_season_for_date)
    if "error" in report:
        print(f"  ERROR — {report['error']}")
        return 1
    print(f"  Fetched {report['games_total']} games from Odds API.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
