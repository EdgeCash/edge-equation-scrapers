#!/usr/bin/env python3
"""
Edge Equation — MLB Player Props (EXPERIMENTAL sandbox)
========================================================
Standalone runner for the player-props projection pipeline.

⚠️ SANDBOX. Outputs land in `data/experimental/mlb-props/` —
deliberately OUTSIDE `public/` so the website can't surface them.
Per BRAND_GUIDE Sandbox protocol, no prop market ships to the daily
card or anywhere user-facing until it passes the same gate as
game-level markets (≥+1% ROI AND Brier <0.246 over 200+ bets).

This script is for offline auditing only — to accumulate evidence
about which prop markets carry signal, before any thought of going
live with them.

Usage:
    python run_mlb_props_experimental.py
    python run_mlb_props_experimental.py --date 2026-05-02
"""

from __future__ import annotations

import sys

from exporters.mlb.player_props_experimental import main


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
