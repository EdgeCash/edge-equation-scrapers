"""
NCAAF Multi-Season Backfill Scraper. EXPERIMENTAL.
==================================================
Bulk-collects historical NCAAF game results across multiple seasons
into `data/backfill/ncaaf/<season>/games.json` for offline model
training, calibration, and backtest validation.

Mirrors the MLB backfill pattern:
  - Idempotent: re-running skips seasons whose games.json already exists
  - Single source: ESPN public scoreboard JSON via the existing
    NCAAFGameScraper (no auth, no API key required)
  - Per-week iteration so one bad week doesn't kill the whole season

Volume note: a typical NCAAF season has ~700-800 FBS games across
~16 weeks of regular season + bowl/playoff weeks. Per-season runtime
~1-2 minutes (one ESPN call per week, ~16 calls per season).

NOT scheduled. NOT auto-fetched. One-time bulk collection to fuel
the projection model + backtest engine ahead of the 2026-27 season.

Usage:
    scraper = NCAAFBackfillScraper(output_root=Path("data/backfill/ncaaf"))
    scraper.fetch_seasons([2021, 2022, 2023, 2024, 2025])
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from scrapers.ncaaf.ncaaf_game_scraper import (
    NCAAFGameScraper, NCAAF_REGULAR_WEEKS,
)

# ESPN season-type codes. We pull regular + postseason in separate
# calls because the API uses different `seasontype` values for each
# (2 = regular, 3 = bowls/playoff).
SEASON_TYPE_REGULAR = 2
SEASON_TYPE_POSTSEASON = 3

# Postseason rarely runs more than ~5 weeks (bowl season + playoff
# rounds). Iterating to 6 is safe overhead.
POSTSEASON_MAX_WEEKS = 6


class NCAAFBackfillScraper:
    """Multi-season NCAAF game-results harvester."""

    def __init__(self, output_root: Path):
        self.output_root = Path(output_root)
        self.game_scraper = NCAAFGameScraper()

    # ---------------- public ---------------------------------------------

    def fetch_seasons(
        self,
        seasons: Iterable[int],
        include_postseason: bool = True,
        verbose: bool = True,
    ) -> dict[int, dict]:
        """Fetch games for each season. Returns per-season report:
            {2024: {"games": int, "regular": int, "postseason": int}, ...}
        """
        report: dict[int, dict] = {}
        for season in seasons:
            if verbose:
                print(f"\n=== NCAAF Season {season} ===")
            games = self.fetch_season_games(
                season,
                include_postseason=include_postseason,
                verbose=verbose,
            )
            n_reg = sum(1 for g in games if g.get("season_type") == "Regular Season")
            n_post = sum(1 for g in games if g.get("season_type") == "Postseason")
            report[season] = {
                "games": len(games),
                "regular": n_reg,
                "postseason": n_post,
            }
        return report

    def fetch_season_games(
        self,
        season: int,
        include_postseason: bool = True,
        verbose: bool = True,
    ) -> list[dict]:
        """Pull every completed FBS game for a season's regular schedule
        plus (optionally) bowls + playoff. Persists to disk; idempotent."""
        path = self.output_root / str(season) / "games.json"
        if path.exists():
            if verbose:
                rel = path.relative_to(self.output_root.parent)
                print(f"  Games already cached at {rel}; loading from disk.")
            try:
                return json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                if verbose:
                    print(f"  Cache unreadable; re-fetching.")

        all_games: list[dict] = []

        if verbose:
            print(f"  Fetching {NCAAF_REGULAR_WEEKS} weeks of regular season...")
        regular = self.game_scraper.fetch_season(
            season,
            season_type=SEASON_TYPE_REGULAR,
            weeks=NCAAF_REGULAR_WEEKS,
        )
        all_games.extend(regular)
        if verbose:
            print(f"    {len(regular)} regular-season games fetched")

        if include_postseason:
            if verbose:
                print(f"  Fetching postseason (bowls + playoff)...")
            post_games: list[dict] = []
            for week in range(1, POSTSEASON_MAX_WEEKS + 1):
                try:
                    week_games = self.game_scraper.fetch_week(
                        season, week, season_type=SEASON_TYPE_POSTSEASON,
                    )
                    post_games.extend(week_games)
                except Exception:
                    continue
            all_games.extend(post_games)
            if verbose:
                print(f"    {len(post_games)} postseason games fetched")

        # De-dup by game_id in case any week-edge games appeared twice.
        seen: set[str] = set()
        unique: list[dict] = []
        for g in all_games:
            gid = g.get("game_id")
            if gid and gid in seen:
                continue
            if gid:
                seen.add(gid)
            unique.append(g)

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(unique, indent=2, default=str))
        if verbose:
            rel = path.relative_to(self.output_root.parent)
            print(f"  Persisted {len(unique)} games to {rel}")
        return unique
