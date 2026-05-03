#!/usr/bin/env python3
"""
Edge Equation — MLB Person Handedness Backfill (one-shot, ~1 minute)
====================================================================
Bulk-harvests pitchHand + batSide for every player ID present in the
season splits files on disk. Required by the handedness-aware props
projector — boxscores expose only player IDs, not handedness, so we
need a separate lookup table.

⚠️ Not a cron. Idempotent — already-cached IDs are skipped.

Prerequisite: splits.json files on disk (run the splits-backfill
workflow first).

Usage:
    python run_mlb_people_backfill.py
    python run_mlb_people_backfill.py --request-interval 0.3
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scrapers.mlb.mlb_people_scraper import (
    MLBPersonScraper, DEFAULT_REQUEST_INTERVAL_S, DEFAULT_BATCH_SIZE,
)


BACKFILL_DIR = REPO_ROOT / "data" / "backfill" / "mlb"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="MLB person-handedness backfill (one-shot, ~1 min)",
    )
    parser.add_argument(
        "--request-interval", type=float, default=DEFAULT_REQUEST_INTERVAL_S,
        help=f"Seconds between API calls. Default {DEFAULT_REQUEST_INTERVAL_S}.",
    )
    parser.add_argument(
        "--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
        help=f"Player IDs per bulk request. Default {DEFAULT_BATCH_SIZE}.",
    )
    parser.add_argument(
        "--backfill-dir", type=str, default=str(BACKFILL_DIR),
    )
    args = parser.parse_args(argv)

    print("\n=== MLB Person Handedness Backfill ===")
    print(f"  Backfill dir:     {args.backfill_dir}")
    print(f"  Request interval: {args.request_interval}s")
    print(f"  Batch size:       {args.batch_size} ids/call\n")

    scraper = MLBPersonScraper(
        backfill_root=Path(args.backfill_dir),
        batch_size=args.batch_size,
        request_interval_s=args.request_interval,
    )
    meta = scraper.run()

    print("\n=== Summary ===")
    print(f"  players cached: {meta.get('n_players', 0):,}")
    print(f"  errors:         {meta.get('n_errors', 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
