"""
MLB Player Props Scraper. EXPERIMENTAL.
=======================================
Slate-driven player stats fetcher for prop projections. For each game
on today's slate, we need:

  - Each starting pitcher's K/9, IP, starts, BAA
  - Each starting batter's AVG, SLG, AB
  - Opposing-team K rate (for pitcher Ks)

This module wires those calls up. Output shape mirrors the structure
already in use by `mlb_pitcher_scraper` and `mlb_lineup_scraper` so
downstream code stays consistent.

Per-day API call cost is significant — ~30 SP calls + ~270 batter
calls (~9 starters × ~15 games × 2 sides) — but statsapi.mlb.com is
unmetered. Per-instance caching keeps re-runs cheap.

EXPERIMENTAL: not wired into the live daily card. Outputs land in
`data/experimental/mlb-props/`. See BRAND_GUIDE Sandbox section.
"""

from __future__ import annotations

import requests

from .mlb_pitcher_scraper import _ip_to_float, TEAM_CODE_TO_ID
from .mlb_lineup_scraper import MLBLineupScraper

BASE_URL = "https://statsapi.mlb.com/api/v1"


class MLBPlayerPropsScraper:
    """Fetches the per-player stats needed to project today's player props."""

    def __init__(self, season: int = 2026):
        self.season = season
        self.base_url = BASE_URL
        self._pitcher_stat_cache: dict[int, dict] = {}
        self._batter_stat_cache: dict[int, dict] = {}
        self._team_k_rate_cache: dict[int, float] = {}
        self._lineup_scraper = MLBLineupScraper(season=season)

    # ---------------- pitcher stats --------------------------------------

    def fetch_pitcher_stats(self, pitcher_id: int) -> dict | None:
        """Season pitching stats for a player: K, IP, starts, BAA."""
        if pitcher_id in self._pitcher_stat_cache:
            return self._pitcher_stat_cache[pitcher_id]

        url = (
            f"{self.base_url}/people/{pitcher_id}/stats"
            f"?stats=season&season={self.season}&group=pitching"
        )
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException:
            self._pitcher_stat_cache[pitcher_id] = None
            return None

        try:
            splits = payload["stats"][0]["splits"]
        except (KeyError, IndexError):
            self._pitcher_stat_cache[pitcher_id] = None
            return None

        if not splits:
            self._pitcher_stat_cache[pitcher_id] = None
            return None

        stat = splits[0].get("stat", {})
        out = {
            "ks": int(stat.get("strikeOuts") or 0),
            "ip": _ip_to_float(stat.get("inningsPitched")),
            "starts": int(stat.get("gamesStarted") or 0),
            "baa": _safe_float(stat.get("avg")),  # batting avg against
            "era": _safe_float(stat.get("era")),
            "whip": _safe_float(stat.get("whip")),
        }
        self._pitcher_stat_cache[pitcher_id] = out
        return out

    # ---------------- batter stats ---------------------------------------

    def fetch_batter_stats(self, batter_id: int) -> dict | None:
        """Season hitting stats for a player: AVG, SLG, AB."""
        if batter_id in self._batter_stat_cache:
            return self._batter_stat_cache[batter_id]

        url = (
            f"{self.base_url}/people/{batter_id}/stats"
            f"?stats=season&season={self.season}&group=hitting"
        )
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException:
            self._batter_stat_cache[batter_id] = None
            return None

        try:
            splits = payload["stats"][0]["splits"]
        except (KeyError, IndexError):
            self._batter_stat_cache[batter_id] = None
            return None

        if not splits:
            self._batter_stat_cache[batter_id] = None
            return None

        stat = splits[0].get("stat", {})
        out = {
            "avg": _safe_float(stat.get("avg")),
            "slg": _safe_float(stat.get("slg")),
            "obp": _safe_float(stat.get("obp")),
            "ab": int(stat.get("atBats") or 0),
            "hits": int(stat.get("hits") or 0),
            "hr": int(stat.get("homeRuns") or 0),
        }
        self._batter_stat_cache[batter_id] = out
        return out

    # ---------------- team-level pitching context ------------------------

    def fetch_team_k_per_9(self, team_id: int) -> float | None:
        """Team's batters' K/9 rate — proxy for how strikeout-prone their
        lineup is. Used as the opponent context for pitcher K projections.
        """
        if team_id in self._team_k_rate_cache:
            return self._team_k_rate_cache[team_id]

        url = (
            f"{self.base_url}/teams/{team_id}/stats"
            f"?stats=season&season={self.season}&group=hitting"
        )
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException:
            self._team_k_rate_cache[team_id] = None
            return None

        try:
            splits = payload["stats"][0]["splits"]
            stat = splits[0].get("stat", {})
            ks = int(stat.get("strikeOuts") or 0)
            pa = int(stat.get("plateAppearances") or 0)
        except (KeyError, IndexError, TypeError, ValueError):
            self._team_k_rate_cache[team_id] = None
            return None

        if pa <= 0:
            self._team_k_rate_cache[team_id] = None
            return None

        # K/PA × ~38 PA per game ≈ K/G; ÷ 9 innings = K/9 from offense's
        # perspective (rough but works for prop adjustments).
        k_per_pa = ks / pa
        k_per_9 = k_per_pa * 38 / 9
        self._team_k_rate_cache[team_id] = k_per_9
        return k_per_9

    # ---------------- combined per-slate -------------------------------

    def fetch_for_slate(
        self,
        slate: list[dict],
        sp_map: dict[int, dict] | None = None,
    ) -> dict[int, dict]:
        """Returns {game_pk: {away: {pitcher, batters, team_k_per_9},
                              home: {pitcher, batters, team_k_per_9}}}.

        sp_map: optional pre-fetched SP info from MLBPitcherScraper to
        avoid double-fetching probable pitcher IDs.
        """
        out: dict[int, dict] = {}
        sp_map = sp_map or {}

        for g in slate:
            game_pk = g.get("game_pk")
            if game_pk is None:
                continue
            away = g.get("away_team")
            home = g.get("home_team")

            # Probable pitchers — reuse from sp_map when available.
            sides = sp_map.get(game_pk, {}) if sp_map else {}
            away_sp_id = (sides.get("away") or {}).get("id")
            home_sp_id = (sides.get("home") or {}).get("id")

            # Lineups (may be None if not posted yet)
            lineup = self._lineup_scraper.fetch_game_lineup(game_pk) or {
                "away": [], "home": [],
            }

            # Team-level K rates (opponent context for SP K projections)
            away_team_id = TEAM_CODE_TO_ID.get(away)
            home_team_id = TEAM_CODE_TO_ID.get(home)
            away_k_per_9 = (
                self.fetch_team_k_per_9(away_team_id) if away_team_id else None
            )
            home_k_per_9 = (
                self.fetch_team_k_per_9(home_team_id) if home_team_id else None
            )

            out[game_pk] = {
                "away_team": away,
                "home_team": home,
                "away": {
                    "pitcher_id": away_sp_id,
                    "pitcher_name": (sides.get("away") or {}).get("name"),
                    "pitcher_stats": (
                        self.fetch_pitcher_stats(away_sp_id) if away_sp_id else None
                    ),
                    "batter_ids": list(lineup.get("away") or []),
                    "team_k_per_9": away_k_per_9,
                },
                "home": {
                    "pitcher_id": home_sp_id,
                    "pitcher_name": (sides.get("home") or {}).get("name"),
                    "pitcher_stats": (
                        self.fetch_pitcher_stats(home_sp_id) if home_sp_id else None
                    ),
                    "batter_ids": list(lineup.get("home") or []),
                    "team_k_per_9": home_k_per_9,
                },
            }
        return out


def _safe_float(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
