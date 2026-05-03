#!/usr/bin/env python3
"""
Edge Equation — NCAAF Multi-Season Backfill (one-time bulk pull)
================================================================
Pulls historical NCAAF FBS game results across multiple seasons into
`data/backfill/ncaaf/<season>/games.json`. Used to fuel offline model
training and backtest validation ahead of the 2026-27 season.

Source: ESPN public scoreboard JSON (no auth, no API key required).
Per-season runtime: ~1-2 minutes (one API call per week × ~16 weeks
regular + ~6 postseason weeks).

⚠️ Not a cron. Run manually when you want fresh historical data.
Idempotent — re-running skips seasons whose games.json already exists.

Usage:
    # Default: 5 most recent completed seasons
    python run_ncaaf_backfill.py

    # Subset
    python run_ncaaf_backfill.py --seasons 2021,2022,2023,2024,2025
    python run_ncaaf_backfill.py --seasons 2021-2025

    # Skip postseason
    python run_ncaaf_backfill.py --no-postseason

    # Custom output dir
    python run_ncaaf_backfill.py --output-dir /path/to/backfill
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scrapers.ncaaf.ncaaf_backfill_scraper import NCAAFBackfillScraper


DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "backfill" / "ncaaf"


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
    """The 5 most recent COMPLETED NCAAF seasons. Note: NCAAF "season"
    convention uses the year the season started (2025 season runs Aug
    2025 → Jan 2026). We exclude any in-progress season."""
    current_year = datetime.utcnow().year
    # If we're past August, current_year's season is in progress; otherwise
    # the previous year's season just finished its postseason in Jan.
    if datetime.utcnow().month >= 8:
        last_complete = current_year - 1
    else:
        last_complete = current_year - 1
    return list(range(last_complete - 4, last_complete + 1))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="NCAAF multi-season backfill (game results from ESPN)",
    )
    parser.add_argument(
        "--seasons", type=str, default="",
        help="Seasons to fetch. e.g. '2021,2022,2023' or '2021-2025'. "
             "Default: the 5 most recent completed seasons.",
    )
    parser.add_argument(
        "--no-postseason", action="store_true", default=False,
        help="Skip postseason (bowl + playoff) weeks. Default: include.",
    )
    parser.add_argument(
        "--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR),
    )
    args = parser.parse_args(argv)

    seasons = parse_seasons(args.seasons) or default_seasons()

    print(f"\nNCAAF Backfill — seasons {seasons}")
    print(f"  Output dir: {args.output_dir}")
    print(f"  Include postseason: {not args.no_postseason}")
    print()

    scraper = NCAAFBackfillScraper(output_root=Path(args.output_dir))
    report = scraper.fetch_seasons(
        seasons,
        include_postseason=not args.no_postseason,
    )

    print("\n=== Summary ===")
    for season, stats in sorted(report.items()):
        print(
            f"  {season}: {stats['games']:>4d} games "
            f"(regular {stats['regular']:>3d}, postseason {stats['postseason']:>2d})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
