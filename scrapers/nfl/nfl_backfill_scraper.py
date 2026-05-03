"""
NFL Multi-Season Backfill Scraper. EXPERIMENTAL.
================================================
Bulk-collects historical NFL game results across multiple seasons
into `data/backfill/nfl/<season>/games.json` for offline model
training, calibration, and backtest validation ahead of the 2026-27
NFL season (kickoff September 2026).

Mirrors the MLB + NCAAF backfill patterns:
  - Idempotent: re-running skips seasons whose games.json already exists
  - Single source: ESPN public scoreboard JSON via the existing
    NFLGameScraper (no auth, no API key required)
  - Per-week iteration so one bad week doesn't kill the whole season

Volume note: a typical NFL season has 272 regular-season games (32
teams × 17 games / 2) across 18 weeks (one bye week per team), plus
13 postseason games (6 wild card + 4 divisional + 2 conference + 1
Super Bowl) = ~285 games total. Per-season runtime ~30 seconds at
one ESPN call per week.

NOT scheduled. NOT auto-fetched. One-time bulk collection to fuel
the projection model + backtest engine when football season approaches.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from scrapers.nfl.nfl_game_scraper import (
    NFLGameScraper, NFL_REGULAR_WEEKS,
    SEASON_TYPE_REGULAR, SEASON_TYPE_POSTSEASON,
)

# Postseason: wild card, divisional, conference championship, Super Bowl.
# Iterating to 5 covers all four with one slot of safety overhead.
POSTSEASON_MAX_WEEKS = 5


class NFLBackfillScraper:
    """Multi-season NFL game-results harvester."""

    def __init__(self, output_root: Path):
        self.output_root = Path(output_root)
        self.game_scraper = NFLGameScraper()

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
                print(f"\n=== NFL Season {season} ===")
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
        """Pull every completed game for a season's regular schedule plus
        (optionally) playoffs. Persists to disk; idempotent."""
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
            print(f"  Fetching {NFL_REGULAR_WEEKS} weeks of regular season...")
        regular = self.game_scraper.fetch_season(
            season,
            season_type=SEASON_TYPE_REGULAR,
            weeks=NFL_REGULAR_WEEKS,
        )
        all_games.extend(regular)
        if verbose:
            print(f"    {len(regular)} regular-season games fetched")

        if include_postseason:
            if verbose:
                print(f"  Fetching postseason (wild card → Super Bowl)...")
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
