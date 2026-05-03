#!/usr/bin/env python3
"""
Edge Equation — MLB Platoon Splits Backfill (one-time bulk pull)
================================================================
Per-player vs-LHP / vs-RHP splits for every player who appeared in
each requested season. Required by Tier-1 props feature work — the
single biggest gap in the current player-prop projector.

⚠️ Not a cron. Run manually (or via the
`mlb-splits-backfill.yml` workflow) when you want fresh splits.
Idempotent — already-completed seasons are skipped, and within a
season already-fetched players resume from a partial file on disk.

Prerequisite: each requested season needs `boxscores.tar.gz` already
on disk (run the MLB Backfill workflow with --with-boxscores first).
We use the boxscore tarball to discover the player list rather than
hitting another API endpoint.

Usage:
    # All seasons with boxscores on disk
    python run_mlb_splits_backfill.py

    # Subset
    python run_mlb_splits_backfill.py --seasons 2022,2023,2024
    python run_mlb_splits_backfill.py --seasons 2022-2025

    # Faster/slower API pace
    python run_mlb_splits_backfill.py --request-interval 0.3
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scrapers.mlb.mlb_splits_scraper import (
    MLBSplitsScraper, DEFAULT_REQUEST_INTERVAL_S,
)


BACKFILL_DIR = REPO_ROOT / "data" / "backfill" / "mlb"


def parse_seasons(spec: str) -> list[int]:
    spec = spec.strip()
    if not spec:
        return []
    if "-" in spec and "," not in spec:
        start, end = spec.split("-", 1)
        return list(range(int(start), int(end) + 1))
    return [int(s.strip()) for s in spec.split(",") if s.strip()]


def discover_seasons() -> list[int]:
    """Every season that has a boxscore tarball on disk (the one
    prerequisite for splits harvesting)."""
    if not BACKFILL_DIR.exists():
        return []
    out: list[int] = []
    for child in BACKFILL_DIR.iterdir():
        if child.is_dir() and child.name.isdigit():
            if (child / "boxscores.tar.gz").exists():
                out.append(int(child.name))
    return sorted(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="MLB platoon splits backfill (vL/vR per player per season)",
    )
    parser.add_argument(
        "--seasons", type=str, default="",
        help="Seasons to fetch. e.g. '2022,2023,2024' or '2022-2024'. "
             "Default: every season with boxscores on disk.",
    )
    parser.add_argument(
        "--request-interval", type=float, default=DEFAULT_REQUEST_INTERVAL_S,
        help=f"Seconds between API calls. Default {DEFAULT_REQUEST_INTERVAL_S}.",
    )
    parser.add_argument(
        "--backfill-dir", type=str, default=str(BACKFILL_DIR),
        help="Root directory containing per-season boxscore tarballs.",
    )
    args = parser.parse_args(argv)

    seasons = parse_seasons(args.seasons) or discover_seasons()
    if not seasons:
        print("No seasons with boxscores found. Run the MLB Backfill workflow")
        print("with --with-boxscores first.")
        return 1

    print("\n=== MLB Platoon Splits Backfill ===")
    print(f"  Backfill dir:     {args.backfill_dir}")
    print(f"  Seasons:          {seasons}")
    print(f"  Request interval: {args.request_interval}s")
    print(f"  Estimated time:   ~{int(2200 * args.request_interval / 60) + 1} min/season")

    scraper = MLBSplitsScraper(
        backfill_root=Path(args.backfill_dir),
        request_interval_s=args.request_interval,
    )
    report = scraper.fetch_seasons(seasons)

    print("\n=== Summary ===")
    for season in seasons:
        meta = report.get(season, {})
        if meta.get("skipped"):
            print(f"  {season}: already complete on disk; skipped.")
        elif meta.get("error"):
            print(f"  {season}: ERROR — {meta['error']}")
        else:
            print(
                f"  {season}: hitters={meta.get('n_hitters', 0)}, "
                f"pitchers={meta.get('n_pitchers', 0)}, "
                f"errors={meta.get('errors', 0)}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
