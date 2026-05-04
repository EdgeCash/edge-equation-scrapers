#!/usr/bin/env python3
"""
Edge Equation — NBA Historical Lines Backfill
=============================================
Pulls one historical Odds-API snapshot per game-day for every NBA
season we already have games.json for. Persists per-season into
`data/backfill/nba/<season>/lines.json`.

Costs 10 credits per call. Default 3-season pull = ~600 calls =
~6,000 credits.

Idempotent: re-runs skip game-days already covered.

Usage:
    ODDS_API_KEY=... python run_nba_lines_backfill.py
    ODDS_API_KEY=... python run_nba_lines_backfill.py --seasons 2023-2025
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scrapers.odds_api.odds_api_backfill_scraper import OddsApiBackfillScraper
from scrapers.odds_api.team_mappings import NBA_TEAM_NAMES

SPORT_KEY = "basketball_nba"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "backfill" / "nba"
DEFAULT_QUOTA_LOG = REPO_ROOT / "public" / "data" / "nba" / "quota_log.json"


def parse_seasons(spec: str) -> list[int]:
    spec = spec.strip()
    if not spec:
        return []
    if "-" in spec and "," not in spec:
        a, b = spec.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(s.strip()) for s in spec.split(",") if s.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="NBA multi-season historical lines backfill (Odds API)",
    )
    parser.add_argument("--seasons", type=str, default="2023-2025")
    parser.add_argument("--snapshot-hour-utc", type=int, default=22)
    parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--quota-log", type=str, default=str(DEFAULT_QUOTA_LOG))
    args = parser.parse_args(argv)

    api_key = os.environ.get("ODDS_API_KEY", "").strip()
    if not api_key:
        print("ERROR: ODDS_API_KEY env var is required.", file=sys.stderr)
        return 2

    seasons = parse_seasons(args.seasons)
    if not seasons:
        print("ERROR: --seasons produced no valid seasons.", file=sys.stderr)
        return 2

    print(f"\nNBA Historical Lines Backfill")
    print(f"  Seasons:        {seasons}")
    print(f"  Snapshot hour:  {args.snapshot_hour_utc:02d}:00 UTC")
    print(f"  Output dir:     {args.output_dir}\n")

    scraper = OddsApiBackfillScraper(
        sport_key=SPORT_KEY,
        team_name_to_code=NBA_TEAM_NAMES,
        output_root=Path(args.output_dir),
        api_key=api_key,
        quota_log_path=Path(args.quota_log),
    )
    report = scraper.fetch_seasons(
        seasons,
        snapshot_hour_utc=args.snapshot_hour_utc,
    )

    print("\n=== Summary ===")
    for season in sorted(report):
        r = report[season]
        if "error" in r:
            print(f"  {season}: ERROR — {r['error']}")
            continue
        print(
            f"  {season}: snapshots={r['snapshots_fetched']:>3d}, "
            f"games_with_lines={r['games_with_lines']:>4d}, "
            f"books_avg={r.get('avg_books', 0):.1f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
