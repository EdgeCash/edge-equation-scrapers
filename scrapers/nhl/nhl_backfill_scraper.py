"""
NHL Multi-Season Backfill Scraper. EXPERIMENTAL.
================================================
Bulk-collects historical NHL game results across multiple seasons
into `data/backfill/nhl/<season>/games.json`. Used to fuel offline
model training and backtest validation.

NHL season convention: a season is named by the year it started.
Season 2024 = Oct 2024 - June 2025 (regular + playoffs). Per-season
date range covers Oct 1 of season N through June 30 of N+1 to
include the Stanley Cup Final.

Strategy:
- Walk the season's date range in weekly chunks (one ESPN call per
  week). Weekly chunks balance call count vs. ESPN's per-call game
  cap (~200 with our limit override).
- Per-season volume: ~1,300 regular-season games + ~85 playoff games
  = ~1,385 games. Across ~37 weeks of date range × 1 call/week = ~37
  ESPN calls per season. ~3 minutes of harvest at typical request
  speed.
- Idempotent: if a season's games.json already exists, the scraper
  skips it.

NOT scheduled. Triggered manually via the matching workflow.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

from scrapers.nhl.nhl_game_scraper import NHLGameScraper


def _season_date_range(season: int) -> tuple[str, str]:
    """NHL season N runs Oct 1 of year N through June 30 of year N+1.
    Covers regular season (Oct-mid-April) plus playoffs (mid-April -
    mid-June)."""
    start = date(season, 10, 1)
    end = date(season + 1, 6, 30)
    return (start.isoformat(), end.isoformat())


def _weekly_chunks(start_date: str, end_date: str) -> list[tuple[str, str]]:
    """Split [start, end] into weekly (Mon-Sun) ranges. Returns a list
    of (start, end) ISO date pairs covering the full window."""
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    out: list[tuple[str, str]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=6), end)
        out.append((cursor.isoformat(), chunk_end.isoformat()))
        cursor = chunk_end + timedelta(days=1)
    return out


class NHLBackfillScraper:
    """Multi-season NHL game-results harvester."""

    def __init__(self, output_root: Path):
        self.output_root = Path(output_root)
        self.game_scraper = NHLGameScraper()

    def fetch_seasons(
        self,
        seasons: Iterable[int],
        verbose: bool = True,
    ) -> dict[int, dict]:
        report: dict[int, dict] = {}
        for season in seasons:
            if verbose:
                print(f"\n=== NHL Season {season} ===")
            games = self.fetch_season_games(season, verbose=verbose)
            report[season] = {
                "games": len(games),
                "completed": sum(1 for g in games if g.get("completed")),
            }
        return report

    def fetch_season_games(
        self, season: int, verbose: bool = True,
    ) -> list[dict]:
        path = self.output_root / str(season) / "games.json"
        if path.exists():
            if verbose:
                rel = path.relative_to(self.output_root.parent)
                print(f"  Already cached at {rel}; loading from disk.")
            try:
                return json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                if verbose:
                    print(f"  Cache unreadable; re-fetching.")

        start_date, end_date = _season_date_range(season)
        chunks = _weekly_chunks(start_date, end_date)
        if verbose:
            print(f"  Window: {start_date} → {end_date}  ({len(chunks)} weekly chunks)")

        all_games: list[dict] = []
        for i, (chunk_start, chunk_end) in enumerate(chunks, 1):
            try:
                week_games = self.game_scraper.fetch_range(chunk_start, chunk_end)
            except Exception:
                continue
            all_games.extend(week_games)
            if verbose and (i % 10 == 0 or i == len(chunks)):
                print(f"    [{i}/{len(chunks)}] {len(all_games)} games so far")

        # De-dup by game_id (ESPN sometimes returns the same game in
        # multiple weekly slices when game date drifts due to TZ).
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
