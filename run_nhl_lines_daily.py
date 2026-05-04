#!/usr/bin/env python3
"""
Edge Equation — NHL Daily Lines Snapshot
========================================
Pulls one LIVE snapshot from The Odds API and merges it into the
current season's lines.json. Designed to run on a cron near peak
pregame (22:30 UTC = 6:30pm ET), but multiple runs per day are
safe — later snapshots overwrite earlier ones so closing-line
entries persist.

Costs 1 credit per call.

Usage:
    ODDS_API_KEY=... python run_nhl_lines_daily.py
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
from scrapers.odds_api.team_mappings import NHL_TEAM_NAMES

SPORT_KEY = "icehockey_nhl"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "backfill" / "nhl"
DEFAULT_QUOTA_LOG = REPO_ROOT / "public" / "data" / "nhl" / "quota_log.json"


def _season_for_date(d: date) -> int:
    """NHL season N = Oct year N → June year N+1."""
    return d.year if d.month >= 10 else d.year - 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NHL daily lines snapshot")
    parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--quota-log", type=str, default=str(DEFAULT_QUOTA_LOG))
    args = parser.parse_args(argv)

    api_key = os.environ.get("ODDS_API_KEY", "").strip()
    if not api_key:
        print("ERROR: ODDS_API_KEY env var is required.", file=sys.stderr)
        return 2

    print("\nNHL Daily Lines Snapshot")
    scraper = OddsApiBackfillScraper(
        sport_key=SPORT_KEY,
        team_name_to_code=NHL_TEAM_NAMES,
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
