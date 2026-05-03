#!/usr/bin/env python3
"""
Edge Equation — NCAAF Historical Lines Backfill (one-time bulk pull)
====================================================================
Pulls per-game multi-book closing + opening lines from
collegefootballdata.com across multiple seasons. Real closing-line
data — what the books actually settled at — used to validate the
projection model against actual market prices.

⚠️ Requires a free CFBD API key. Get one at
https://collegefootballdata.com/key, then either:
  - export CFBD_API_KEY=... before running, or
  - pass --api-key on the command line

Idempotent — already-cached seasons are skipped.

Usage:
    # Default: 5 most recent completed seasons
    python run_ncaaf_lines_backfill.py

    # Subset
    python run_ncaaf_lines_backfill.py --seasons 2021,2022,2023
    python run_ncaaf_lines_backfill.py --seasons 2021-2025

    # Skip postseason
    python run_ncaaf_lines_backfill.py --no-postseason
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scrapers.ncaaf.ncaaf_lines_scraper import (
    CFBDLinesScraper, DEFAULT_REQUEST_INTERVAL_S,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "backfill" / "ncaaf"


def parse_seasons(spec: str) -> list[int]:
    spec = spec.strip()
    if not spec:
        return []
    if "-" in spec and "," not in spec:
        start, end = spec.split("-", 1)
        return list(range(int(start), int(end) + 1))
    return [int(s.strip()) for s in spec.split(",") if s.strip()]


def default_seasons() -> list[int]:
    """Mirror the games-backfill default: 5 most recent completed seasons.
    NCAAF "season" convention: 2025 season runs Aug 2025 → Jan 2026."""
    current_year = datetime.utcnow().year
    last_complete = current_year - 1
    return list(range(last_complete - 4, last_complete + 1))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="NCAAF historical-lines backfill (CFBD)",
    )
    parser.add_argument(
        "--seasons", type=str, default="",
        help="Seasons. e.g. '2021,2022,2023' or '2021-2025'. "
             "Default: 5 most recent completed seasons.",
    )
    parser.add_argument(
        "--no-postseason", action="store_true", default=False,
    )
    parser.add_argument(
        "--api-key", type=str, default=None,
        help="CFBD API key (overrides CFBD_API_KEY env var).",
    )
    parser.add_argument(
        "--request-interval", type=float, default=DEFAULT_REQUEST_INTERVAL_S,
    )
    parser.add_argument(
        "--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR),
    )
    args = parser.parse_args(argv)

    api_key = args.api_key or os.environ.get("CFBD_API_KEY")
    if not api_key:
        print(
            "ERROR: no CFBD API key. Set CFBD_API_KEY env var or pass "
            "--api-key. Get a free key at https://collegefootballdata.com/key"
        )
        return 1

    seasons = parse_seasons(args.seasons) or default_seasons()

    print(f"\nNCAAF Historical Lines Backfill — seasons {seasons}")
    print(f"  Output dir: {args.output_dir}")
    print(f"  Include postseason: {not args.no_postseason}")
    print(f"  Request interval: {args.request_interval}s")

    output_dir = Path(args.output_dir)
    # Drop raw responses next to the output dir for forensics. Workflow
    # uploads them as a separate artifact so failed runs are debuggable
    # without re-running.
    raw_dump_dir = output_dir / "_raw"

    scraper = CFBDLinesScraper(
        output_root=output_dir,
        api_key=api_key,
        request_interval_s=args.request_interval,
    )
    report = scraper.fetch_seasons(
        seasons,
        include_postseason=not args.no_postseason,
        raw_dump_dir=raw_dump_dir,
    )

    print("\n=== Summary ===")
    n_failed = 0
    for season, stats in sorted(report.items()):
        if stats.get("skipped"):
            print(f"  {season}: already complete; skipped.")
        elif stats.get("error"):
            print(f"  {season}: ERROR — {stats['error']}")
            n_failed += 1
        else:
            print(
                f"  {season}: {stats.get('n_games', 0):>4d} games, "
                f"{stats.get('n_with_lines', 0):>4d} have lines, "
                f"avg {stats.get('avg_books_per_game', 0):.1f} books/game"
            )

    # Fail loudly if any season errored. Previously the runner exited 0
    # on per-season errors, which let the workflow's verify step pass
    # over a missing-file situation it should have caught.
    if n_failed:
        print(f"\n{n_failed}/{len(report)} season(s) failed — see raw dumps for response bodies.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
