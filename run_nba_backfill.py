#!/usr/bin/env python3
"""
Edge Equation — NBA Multi-Season Backfill (one-time bulk pull)
==============================================================
Pulls historical NBA game results across multiple seasons into
`data/backfill/nba/<season>/games.json`. Used to fuel cross-sport
infrastructure reuse + offline model training.

NBA season convention: season N = Oct year N → June year N+1.
Default = 5 most recent completed seasons + the in-progress one
(playoffs are happening RIGHT NOW so partial 2024 data is useful).

Source: ESPN public scoreboard JSON (no auth).
Per-season runtime: ~3 min. 5-season run takes ~15 min wall-clock.

Usage:
    python run_nba_backfill.py
    python run_nba_backfill.py --seasons 2020,2021,2022,2023,2024
    python run_nba_backfill.py --seasons 2020-2024
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scrapers.nba.nba_backfill_scraper import NBABackfillScraper


DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "backfill" / "nba"


def parse_seasons(spec: str) -> list[int]:
    spec = spec.strip()
    if not spec:
        return []
    if "-" in spec and "," not in spec:
        start, end = spec.split("-", 1)
        return list(range(int(start), int(end) + 1))
    return [int(s.strip()) for s in spec.split(",") if s.strip()]


def default_seasons() -> list[int]:
    """5 most recent NBA seasons. NBA season N starts Oct of year N.
    If we're past Oct, that year's season is in progress; otherwise
    the previous year's just finished playoffs in June."""
    now = datetime.utcnow()
    if now.month >= 10:
        most_recent = now.year
    else:
        most_recent = now.year - 1
    return list(range(most_recent - 4, most_recent + 1))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="NBA multi-season backfill (game results from ESPN)",
    )
    parser.add_argument("--seasons", type=str, default="")
    parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args(argv)

    seasons = parse_seasons(args.seasons) or default_seasons()

    print(f"\nNBA Backfill — seasons {seasons}")
    print(f"  Output dir: {args.output_dir}\n")

    scraper = NBABackfillScraper(output_root=Path(args.output_dir))
    report = scraper.fetch_seasons(seasons)

    print("\n=== Summary ===")
    for season, stats in sorted(report.items()):
        print(
            f"  {season}: {stats['games']:>5d} games "
            f"({stats['completed']} completed)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
