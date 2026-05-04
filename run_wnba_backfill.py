#!/usr/bin/env python3
"""
Edge Equation — WNBA Multi-Season Backfill (one-time bulk pull)
===============================================================
Pulls historical WNBA game results across multiple seasons into
`data/backfill/wnba/<season>/games.json`.

WNBA season convention: season N occurs entirely in calendar year N.
Default = 5 most recent completed seasons (excludes the in-progress
season since WNBA hasn't started yet for season 2026 as of May 2026).

Source: ESPN public scoreboard JSON (no auth).
Per-season runtime: ~2 min. 5-season run takes ~10 min wall-clock.

Usage:
    python run_wnba_backfill.py
    python run_wnba_backfill.py --seasons 2021,2022,2023,2024,2025
    python run_wnba_backfill.py --seasons 2021-2025
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scrapers.wnba.wnba_backfill_scraper import WNBABackfillScraper


DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "backfill" / "wnba"


def parse_seasons(spec: str) -> list[int]:
    spec = spec.strip()
    if not spec:
        return []
    if "-" in spec and "," not in spec:
        start, end = spec.split("-", 1)
        return list(range(int(start), int(end) + 1))
    return [int(s.strip()) for s in spec.split(",") if s.strip()]


def default_seasons() -> list[int]:
    """5 most recent completed WNBA seasons. WNBA seasons run May-Oct
    in a single calendar year. If we're past November, the current
    year's season just finished; otherwise the previous year's season
    was the most recent complete one."""
    now = datetime.utcnow()
    if now.month >= 11:
        most_recent = now.year
    else:
        most_recent = now.year - 1
    return list(range(most_recent - 4, most_recent + 1))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="WNBA multi-season backfill (game results from ESPN)",
    )
    parser.add_argument("--seasons", type=str, default="")
    parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args(argv)

    seasons = parse_seasons(args.seasons) or default_seasons()

    print(f"\nWNBA Backfill — seasons {seasons}")
    print(f"  Output dir: {args.output_dir}\n")

    scraper = WNBABackfillScraper(output_root=Path(args.output_dir))
    report = scraper.fetch_seasons(seasons)

    print("\n=== Summary ===")
    for season, stats in sorted(report.items()):
        print(
            f"  {season}: {stats['games']:>4d} games "
            f"({stats['completed']} completed)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
