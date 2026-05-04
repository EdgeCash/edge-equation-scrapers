"""
WNBA Multi-Season Backfill Scraper. EXPERIMENTAL.
=================================================
Bulk-collects historical WNBA game results across multiple seasons
into `data/backfill/wnba/<season>/games.json`.

WNBA season convention: a season is named by the year it occurs in
(unlike NHL which spans calendar years). Season N runs roughly May
through October of year N. Per-season date range covers May 1
through October 31 to include playoffs and Finals.

Strategy: walk weekly date chunks (one ESPN call per week × ~26
weeks per season = ~26 calls). Per-season volume ~265 games (240
reg + ~25 playoffs across 12 teams). Per-season runtime ~2 min.

Idempotent: if a season's games.json already exists, the scraper
skips it.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

from scrapers.wnba.wnba_game_scraper import WNBAGameScraper


def _season_date_range(season: int) -> tuple[str, str]:
    """WNBA season N runs roughly May - Oct of year N. We use a wider
    May 1 - Oct 31 window to safely capture preseason, regular,
    playoffs, and Finals."""
    start = date(season, 5, 1)
    end = date(season, 10, 31)
    return (start.isoformat(), end.isoformat())


def _weekly_chunks(start_date: str, end_date: str) -> list[tuple[str, str]]:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    out: list[tuple[str, str]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=6), end)
        out.append((cursor.isoformat(), chunk_end.isoformat()))
        cursor = chunk_end + timedelta(days=1)
    return out


class WNBABackfillScraper:
    """Multi-season WNBA game-results harvester."""

    def __init__(self, output_root: Path):
        self.output_root = Path(output_root)
        self.game_scraper = WNBAGameScraper()

    def fetch_seasons(
        self,
        seasons: Iterable[int],
        verbose: bool = True,
    ) -> dict[int, dict]:
        report: dict[int, dict] = {}
        for season in seasons:
            if verbose:
                print(f"\n=== WNBA Season {season} ===")
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
