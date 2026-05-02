"""
MLB Multi-Season Backfill Scraper. EXPERIMENTAL.
================================================
Bulk-collects historical MLB data for offline model fine-tuning. Two
layers:

  1. **Games** (cheap, ~30 calls per season):
     Season-long schedule + results, including the linescore-derived
     metrics MLBGameScraper already produces (ML, RL, F5, NRFI, totals).
     Persists to: data/backfill/mlb/<season>/games.json

  2. **Boxscores** (heavy, ~2,500 calls per season):
     Per-game lineup + per-player stat line for every batter and
     pitcher who appeared. Required for prop backtest grading. Polite
     rate-limit (1 req / second by default) to be a good citizen of
     the unmetered MLB Stats API.
     Persists to: data/backfill/mlb/<season>/boxscores/<game_pk>.json

Both layers are **idempotent** — re-running the scraper skips already
persisted data so partial-progress runs can resume cleanly.

NOT scheduled. NOT auto-fetched. This is a one-time bulk collection
to fuel offline analysis (calibration refits, prop backtest grading,
multi-season model validation). Once the data lands, we can extend
BacktestEngine + the props pipeline to consume it without any further
API calls.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterable

import requests

from .mlb_game_scraper import MLBGameScraper

BOXSCORE_URL = "https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"

# Rate limit: be polite even though statsapi.mlb.com is unmetered.
# 1 request/second = ~2,500 boxscores in ~42 minutes per season.
DEFAULT_REQUEST_INTERVAL_S = 1.0


class MLBBackfillScraper:
    """Multi-season game results + per-game boxscore harvester."""

    def __init__(
        self,
        output_root: Path,
        request_interval_s: float = DEFAULT_REQUEST_INTERVAL_S,
    ):
        self.output_root = Path(output_root)
        self.request_interval_s = request_interval_s
        self.game_scraper = MLBGameScraper()
        self._last_request_at = 0.0

    # ---------------- public ---------------------------------------------

    def fetch_seasons(
        self,
        seasons: Iterable[int],
        with_boxscores: bool = False,
        verbose: bool = True,
    ) -> dict:
        """Fetch games (and optionally boxscores) for each season.

        Returns a small report dict per season:
            {2024: {"games": int, "boxscores_fetched": int,
                    "boxscores_skipped": int, "boxscores_failed": int}, ...}
        """
        report: dict[int, dict] = {}
        for season in seasons:
            if verbose:
                print(f"\n=== Season {season} ===")
            games = self.fetch_season_games(season, verbose=verbose)
            entry = {
                "games": len(games),
                "boxscores_fetched": 0,
                "boxscores_skipped": 0,
                "boxscores_failed": 0,
            }
            if with_boxscores:
                box_report = self.fetch_season_boxscores(
                    season, games, verbose=verbose,
                )
                entry.update(box_report)
            report[season] = entry
        return report

    # ---------------- season games ---------------------------------------

    def fetch_season_games(self, season: int, verbose: bool = True) -> list[dict]:
        """Pull every completed game for a season's regular schedule
        (March 20 → November 5 covers regular + postseason). Returns
        the parsed game list (also persisted to disk).
        """
        path = self.output_root / str(season) / "games.json"
        if path.exists():
            if verbose:
                print(f"  Games already cached at {path.relative_to(self.output_root.parent)}; loading from disk.")
            try:
                return json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                if verbose:
                    print(f"  Cache unreadable; re-fetching.")

        if verbose:
            print(f"  Fetching games for {season}...")
        games = self.game_scraper.fetch_schedule(
            f"{season}-03-20", f"{season}-11-05",
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(games, indent=2, default=str))
        if verbose:
            print(f"  Persisted {len(games)} games to {path.relative_to(self.output_root.parent)}")
        return games

    # ---------------- per-game boxscores ---------------------------------

    def fetch_season_boxscores(
        self,
        season: int,
        games: list[dict],
        verbose: bool = True,
    ) -> dict:
        """Fetch + persist per-game boxscore for every game in the season.

        Idempotent: per-game JSON files already on disk are skipped.
        Rate-limited per `self.request_interval_s`.
        """
        out_dir = self.output_root / str(season) / "boxscores"
        out_dir.mkdir(parents=True, exist_ok=True)

        report = {
            "boxscores_fetched": 0,
            "boxscores_skipped": 0,
            "boxscores_failed": 0,
        }
        total = len(games)
        for i, g in enumerate(games, 1):
            game_pk = g.get("game_pk")
            if not game_pk:
                continue
            path = out_dir / f"{game_pk}.json"
            if path.exists():
                report["boxscores_skipped"] += 1
                continue

            box = self._fetch_boxscore(game_pk)
            if box is None:
                report["boxscores_failed"] += 1
                if verbose:
                    print(f"  [{i}/{total}] boxscore {game_pk} FAILED")
                continue

            path.write_text(json.dumps(box, indent=2, default=str))
            report["boxscores_fetched"] += 1

            if verbose and i % 50 == 0:
                print(
                    f"  [{i}/{total}] season {season} boxscores: "
                    f"+{report['boxscores_fetched']} new, "
                    f"{report['boxscores_skipped']} skipped, "
                    f"{report['boxscores_failed']} failed"
                )

        if verbose:
            print(
                f"  Season {season} boxscores complete: "
                f"+{report['boxscores_fetched']} new, "
                f"{report['boxscores_skipped']} cached, "
                f"{report['boxscores_failed']} failed"
            )
        return report

    # ---------------- internals ------------------------------------------

    def _fetch_boxscore(self, game_pk: int) -> dict | None:
        """Single boxscore fetch with rate limiting."""
        self._throttle()
        try:
            resp = requests.get(
                BOXSCORE_URL.format(game_pk=game_pk),
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException:
            return None

    def _throttle(self) -> None:
        """Sleep just enough to maintain the configured request interval."""
        if self.request_interval_s <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        wait = self.request_interval_s - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()
