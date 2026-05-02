#!/usr/bin/env python3
"""
Edge Equation — MLB Daily Pipeline (entry point)
================================================
Top-level convenience runner. Chains the full daily build:

    1. Fetch season-to-date backfill (game results)
    2. Fetch today's slate
    3. Pull probable starting pitchers + recent form
    4. Pull team bullpen factors
    5. Pull weather for outdoor venues
    6. Pull market odds (The Odds API → DraftKings fallback)
    7. Pull day-of lineups + flag star scratches
    8. Run season backtest (computes calibration + Brier per market)
    9. Project today's slate using calibrated constants
    10. Build all 8 spreadsheet tabs (Today's Card, 6 bet types, Backtest)
    11. Apply BRAND_GUIDE market gate + per-market edge thresholds
    12. Auto-grade any picks whose game completed since last run
    13. Snap CLV summary + write outputs to public/data/mlb/

Idempotent: safe to re-run. The picks log dedupes on pick_id and the
auto-grader skips already-graded entries.

Usage:
    python run_mlb_daily.py                    # today, no git push
    python run_mlb_daily.py --date 2026-05-02  # specific date
    python run_mlb_daily.py --no-odds          # skip the odds fetch
    python run_mlb_daily.py --push             # commit + push outputs

All flags supported by the underlying daily_spreadsheet module work
here too — this file is a thin pass-through. See:
    python run_mlb_daily.py --help
"""

from __future__ import annotations

import sys

from exporters.mlb.daily_spreadsheet import main


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
