"""
Closing Line Snapshot
=====================
Re-fetches market odds and records the current price for every pick in
public/data/mlb/picks_log.json that's still awaiting a closing snapshot.
Computes CLV (closing line value) per pick and writes back.

Designed to be run on a separate cron from the morning daily build —
something like every 30 minutes from 30 minutes before first pitch
through end-of-slate. Each pick's closing-price field is set the first
time the script sees it priced; subsequent runs skip already-snapped
picks (idempotent).

Usage:
    python -m exporters.mlb.closing_snapshot
    python -m exporters.mlb.closing_snapshot --no-push
    python -m exporters.mlb.closing_snapshot --output-dir public/data/mlb
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scrapers.mlb.mlb_odds_scraper import MLBOddsScraper
from exporters.mlb.clv_tracker import ClvTracker

DEFAULT_OUTPUT_DIR = REPO_ROOT / "public" / "data" / "mlb"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Snap MLB closing lines for tracked picks")
    parser.add_argument(
        "--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR),
    )
    parser.add_argument(
        "--odds-api-key", type=str, default=None,
        help="The Odds API key (overrides ODDS_API_KEY env var)",
    )
    parser.add_argument(
        "--push", action="store_true", default=False,
        help="git add/commit/push picks_log.json after snapping",
    )
    parser.add_argument(
        "--branch", type=str, default=None,
    )
    parser.add_argument(
        "--window-min", type=int, default=90,
        help="Only fetch odds if any unsettled pick's game starts within "
             "this many minutes (default 90). Set 0 to disable the gate.",
    )
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    tracker = ClvTracker(output_dir)

    print(f"MLB Closing-Line Snapshot — {datetime.utcnow().isoformat()}Z")
    print(f"  Loading picks log from {tracker.path}...")
    initial = tracker.load()
    print(f"    {len(initial['picks'])} picks logged total")

    # Smart gate: skip the API call when there's nothing to snap. Saves
    # ~70-80% of closing-snapshot API calls on the average MLB day.
    window = args.window_min or None
    pending = tracker.pending_today(max_minutes_to_first_pitch=window)
    if not pending:
        print(
            f"  No unsettled picks within {args.window_min}-min window; "
            "skipping odds fetch (saves an API call)."
        )
        return 0
    print(f"  {len(pending)} unsettled pick(s) within the window")

    print("  Fetching market odds...")
    odds_scraper = MLBOddsScraper(
        api_key=args.odds_api_key,
        quota_log_path=output_dir / "quota_log.json",
    )
    odds = odds_scraper.fetch()
    print(f"    {odds['source']} -> {len(odds['games'])} priced games")

    report = tracker.record_closing_lines(odds)
    print(f"  Snapped: {report['snapped_today']} pick(s)")
    print(f"  Skipped (no matching market): {report['skipped_no_match']}")
    print(f"  Skipped (already had close):  {report['skipped_already_set']}")

    if report["snapped_today"] == 0:
        print("  Nothing to commit.")
        return 0

    # Refresh the standalone summary file so the website / consumers
    # don't have to re-aggregate from the raw picks_log every time.
    summary = tracker.save_summary()
    o = summary.get("clv_overall") or {}
    print(
        f"  Summary refreshed: {summary['picks_with_close']}/"
        f"{summary['picks_total']} picks have a close; "
        f"mean CLV {o.get('mean_clv_pct')}"
    )

    if args.push:
        rel_log = str(tracker.path.relative_to(REPO_ROOT))
        rel_summary = str(tracker.summary_path.relative_to(REPO_ROOT))
        try:
            subprocess.run(
                ["git", "-C", str(REPO_ROOT), "add", rel_log, rel_summary],
                check=True, capture_output=True, text=True,
            )
            msg = (
                f"Closing-line snapshot — "
                f"{report['snapped_today']} pick(s) "
                f"@ {datetime.utcnow().strftime('%H:%M')}Z"
            )
            subprocess.run(
                ["git", "-C", str(REPO_ROOT), "commit", "-m", msg],
                check=True, capture_output=True, text=True,
            )
            push_cmd = ["git", "-C", str(REPO_ROOT), "push"]
            if args.branch:
                push_cmd += ["-u", "origin", args.branch]
            subprocess.run(push_cmd, check=True, capture_output=True, text=True)
            print(f"  Pushed: {msg}")
        except subprocess.CalledProcessError as e:
            print(f"  git failed: {e.stderr or e.stdout}")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
