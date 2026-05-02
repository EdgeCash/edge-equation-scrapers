"""
MLB Lineup Scraper
==================
Day-of lineup intelligence. For each game on the slate we determine:

1. The team's "stars" — top-N hitters by season OPS
2. Today's posted batting order (when available)
3. How many stars are missing → an offensive adjustment factor

Why this matters: a team with its ace hitter scratched plays materially
worse than the team's season averages suggest. The 11 AM ET cron gives
lineups time to post for most afternoon and night games before
publication.

Adjustment is intentionally small (4% reduction per missing star, max 3
stars). One missing bat out of 9 only does so much; this is meant as a
nudge, not a hammer. When the lineup hasn't been posted yet (early-day
runs, doubleheaders) the factor falls back to 1.0 — no adjustment.
"""

from __future__ import annotations

from typing import Iterable

import requests

from .mlb_pitcher_scraper import TEAM_CODE_TO_ID

BASE_URL = "https://statsapi.mlb.com/api/v1"

# How many top-OPS hitters to track per team as "stars"
TOP_STARS_PER_TEAM = 3

# Run-projection reduction per missing star
PER_STAR_MISSING_PENALTY = 0.04
LINEUP_FACTOR_FLOOR = 0.85   # never drop below 15% reduction
LINEUP_FACTOR_CEILING = 1.0  # we don't reward "extra stars" — capped at neutral


def lineup_factor(stars_total: int, stars_present: int) -> float:
    """Convert (stars present out of total) into a multiplier on a team's
    projected offensive output.

    All stars present → 1.0 (no adjustment).
    Each missing star → -4% on the team's offense, floored at 0.85.
    """
    if stars_total <= 0:
        return 1.0
    missing = max(0, stars_total - stars_present)
    f = LINEUP_FACTOR_CEILING - missing * PER_STAR_MISSING_PENALTY
    return max(LINEUP_FACTOR_FLOOR, min(LINEUP_FACTOR_CEILING, f))


class MLBLineupScraper:
    """Pulls per-team star hitters + per-game lineups; derives offense
    adjustments from missing stars."""

    def __init__(self, season: int = 2026):
        self.season = season
        self.base_url = BASE_URL
        self._stars_cache: dict[int, list[dict]] = {}
        self._lineup_cache: dict[int, dict] = {}

    # ---------------- top hitters per team --------------------------------

    def fetch_team_top_hitters(
        self, team_id: int, n: int = TOP_STARS_PER_TEAM,
    ) -> list[dict]:
        """Top-N qualified hitters for the team this season, ranked by OPS.

        Returns a list of {"id": int, "name": str, "ops": float}. Empty
        list on network failure or insufficient data — callers should
        treat that as "no star adjustment for this team."
        """
        if team_id in self._stars_cache:
            return self._stars_cache[team_id]

        # statsapi sortStat ranks players in the queried scope by the
        # named stat. playerPool=Q restricts to qualified hitters so
        # we don't end up flagging a 30-AB call-up as a "star."
        url = (
            f"{self.base_url}/stats"
            f"?stats=season&season={self.season}&group=hitting"
            f"&teamId={team_id}&playerPool=Q"
            f"&sortStat=onBasePlusSlugging&order=desc&limit={n}"
        )
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException:
            self._stars_cache[team_id] = []
            return []

        try:
            splits = payload["stats"][0]["splits"]
        except (KeyError, IndexError):
            self._stars_cache[team_id] = []
            return []

        stars: list[dict] = []
        for s in splits:
            stat = s.get("stat") or {}
            player = s.get("player") or {}
            try:
                ops = float(stat.get("ops") or 0)
            except (TypeError, ValueError):
                ops = 0.0
            pid = player.get("id")
            if not pid:
                continue
            stars.append({
                "id": pid,
                "name": player.get("fullName"),
                "ops": ops,
            })
        self._stars_cache[team_id] = stars
        return stars

    # ---------------- per-game lineup -------------------------------------

    def fetch_game_lineup(self, game_pk: int) -> dict | None:
        """Today's posted batting order for both sides of a game.

        Returns {"away": [player_ids...], "home": [...]} when the
        boxscore exposes a lineup, or None when the lineup isn't
        posted yet (common early in the day or for doubleheaders).
        """
        if game_pk in self._lineup_cache:
            return self._lineup_cache[game_pk]

        url = f"{self.base_url}/game/{game_pk}/boxscore"
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException:
            self._lineup_cache[game_pk] = None
            return None

        teams = payload.get("teams") or {}
        away_batters = (teams.get("away") or {}).get("batters") or []
        home_batters = (teams.get("home") or {}).get("batters") or []

        # An empty list typically means the lineup hasn't been posted yet.
        if not away_batters and not home_batters:
            self._lineup_cache[game_pk] = None
            return None

        out = {"away": list(away_batters), "home": list(home_batters)}
        self._lineup_cache[game_pk] = out
        return out

    # ---------------- combined ----------------------------------------

    def fetch_for_slate(self, slate: list[dict]) -> dict[int, dict]:
        """For each game in the slate, return per-side lineup adjustment:

            {game_pk: {
                "away": {"stars_total": int, "stars_present": int,
                         "missing_stars": [names], "factor": float},
                "home": {...}
            }}

        Missing data on either side cleanly defaults to factor 1.0.
        """
        out: dict[int, dict] = {}
        for g in slate:
            game_pk = g.get("game_pk")
            away = g.get("away_team")
            home = g.get("home_team")
            if game_pk is None:
                continue

            away_id = TEAM_CODE_TO_ID.get(away)
            home_id = TEAM_CODE_TO_ID.get(home)
            away_stars = self.fetch_team_top_hitters(away_id) if away_id else []
            home_stars = self.fetch_team_top_hitters(home_id) if home_id else []

            lineup = self.fetch_game_lineup(game_pk) or {"away": None, "home": None}

            out[game_pk] = {
                "away": _resolve_side(away_stars, lineup.get("away")),
                "home": _resolve_side(home_stars, lineup.get("home")),
            }
        return out


def _resolve_side(stars: list[dict], lineup_ids: list[int] | None) -> dict:
    """Compare a team's star list against today's posted lineup.

    Returns {stars_total, stars_present, missing_stars, factor}.
    When the lineup isn't posted, returns a neutral entry with factor 1.0
    rather than penalizing — we don't know who's playing.
    """
    stars_total = len(stars)
    if lineup_ids is None or not lineup_ids:
        return {
            "stars_total": stars_total,
            "stars_present": stars_total,
            "missing_stars": [],
            "factor": 1.0,
            "lineup_posted": False,
        }
    lineup_set = set(lineup_ids)
    present = [s for s in stars if s["id"] in lineup_set]
    missing = [s for s in stars if s["id"] not in lineup_set]
    return {
        "stars_total": stars_total,
        "stars_present": len(present),
        "missing_stars": [s["name"] for s in missing],
        "factor": lineup_factor(stars_total, len(present)),
        "lineup_posted": True,
    }
