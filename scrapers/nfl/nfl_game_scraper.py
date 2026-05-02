"""
NFL Game Results Scraper
========================
Pulls NFL game schedule + results from ESPN's free scoreboard JSON
(`site.api.espn.com`). Output mirrors the MLB scraper's shape so
downstream model code can reuse the same factor-stacking patterns
once we have enough seasons of NFL data to calibrate against.

Key bet-relevant fields exposed per game:
    - moneyline winner (or null for ties)
    - spread margin (home - away, signed)
    - total points
    - 1H total + 1H winner (for first-half markets)
    - quarter scores (for quarter total markets)

Data source: ESPN public scoreboard JSON. No auth, no documented quota
but generally reliable. Treat as best-effort; back up with a fallback
endpoint (e.g., NFL.com) if reliability becomes an issue.

Usage:
    scraper = NFLGameScraper()
    games = scraper.fetch_date("2025-12-28")
    games = scraper.fetch_week(season=2025, week=17)
    games = scraper.fetch_season(2025)
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from typing import Iterable

import requests

SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
)

# Season types per ESPN: 1 = preseason, 2 = regular, 3 = postseason.
SEASON_TYPE_REGULAR = 2
SEASON_TYPE_POSTSEASON = 3
NFL_REGULAR_WEEKS = 18  # 18 weeks since 2021


class NFLGameScraper:
    """Pulls completed and upcoming NFL games into a normalized shape."""

    def __init__(self):
        self.base_url = SCOREBOARD_URL

    # ---------------- public ---------------------------------------------

    def fetch_date(self, date: str) -> list[dict]:
        """Return all NFL games on the given date (YYYY-MM-DD)."""
        date_compact = date.replace("-", "")
        return self._fetch_and_parse({"dates": date_compact})

    def fetch_week(
        self,
        season: int,
        week: int,
        season_type: int = SEASON_TYPE_REGULAR,
    ) -> list[dict]:
        """Return all games for a season + week. Most useful entry point
        for NFL since the league is week-structured (Sun + Mon + Thu)."""
        return self._fetch_and_parse({
            "dates": str(season),
            "seasontype": season_type,
            "week": week,
        })

    def fetch_season(
        self,
        season: int,
        season_type: int = SEASON_TYPE_REGULAR,
        weeks: int = NFL_REGULAR_WEEKS,
    ) -> list[dict]:
        """All games in a season. Hits the API once per week."""
        out: list[dict] = []
        for week in range(1, weeks + 1):
            try:
                out.extend(self.fetch_week(season, week, season_type=season_type))
            except requests.RequestException:
                continue
        return out

    def fetch_range(self, start_date: str, end_date: str) -> list[dict]:
        """Compact date-range form (ESPN accepts YYYYMMDD-YYYYMMDD)."""
        start = start_date.replace("-", "")
        end = end_date.replace("-", "")
        return self._fetch_and_parse({"dates": f"{start}-{end}"})

    # ---------------- internals ------------------------------------------

    def _fetch_and_parse(self, params: dict) -> list[dict]:
        try:
            resp = requests.get(self.base_url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException:
            return []

        out: list[dict] = []
        for ev in data.get("events", []) or []:
            parsed = self._parse_event(ev)
            if parsed is not None:
                out.append(parsed)
        return out

    @staticmethod
    def _parse_event(event: dict) -> dict | None:
        """Translate one ESPN event into a normalized game dict."""
        try:
            comp = event["competitions"][0]
            competitors = comp.get("competitors", [])
            if len(competitors) < 2:
                return None
            home = next(c for c in competitors if c.get("homeAway") == "home")
            away = next(c for c in competitors if c.get("homeAway") == "away")
        except (KeyError, IndexError, StopIteration):
            return None

        away_team = (away.get("team") or {}).get("abbreviation")
        home_team = (home.get("team") or {}).get("abbreviation")
        if not away_team or not home_team:
            return None

        status = event.get("status", {}) or {}
        status_type = status.get("type", {}) or {}
        completed = bool(status_type.get("completed"))

        try:
            away_score = int(away.get("score", "0") or 0)
            home_score = int(home.get("score", "0") or 0)
        except (TypeError, ValueError):
            away_score = home_score = 0

        # Quarter-by-quarter scores (linescores). Empty until the game
        # progresses past Q1; first-half is the sum of Q1+Q2.
        away_qs = [_safe_int(q.get("value")) for q in away.get("linescores") or []]
        home_qs = [_safe_int(q.get("value")) for q in home.get("linescores") or []]

        # Pad to 4 quarters so callers can index without bounds checks
        while len(away_qs) < 4:
            away_qs.append(0)
        while len(home_qs) < 4:
            home_qs.append(0)

        away_1h = away_qs[0] + away_qs[1]
        home_1h = home_qs[0] + home_qs[1]

        margin = home_score - away_score
        ml_winner = (
            away_team if margin < 0
            else home_team if margin > 0
            else None  # tie
        )

        # Date: ESPN gives ISO; truncate to YYYY-MM-DD for consistency
        # with the MLB scraper.
        raw_date = event.get("date") or comp.get("date") or ""
        date_str = raw_date[:10] if raw_date else None

        return {
            "date": date_str,
            "game_id": str(event.get("id")),
            "season": (event.get("season") or {}).get("year"),
            "week": (event.get("week") or {}).get("number"),
            "season_type": (event.get("season") or {}).get("type"),
            "status": status_type.get("name"),
            "completed": completed,
            "away_team": away_team,
            "home_team": home_team,
            "away_score": away_score,
            "home_score": home_score,
            "total_points": away_score + home_score,
            "ml_winner": ml_winner,
            "margin": margin,                   # signed home - away
            "spread_margin": abs(margin),
            "away_q": away_qs,                  # [Q1, Q2, Q3, Q4]
            "home_q": home_qs,
            "away_1h": away_1h,
            "home_1h": home_1h,
            "first_half_total": away_1h + home_1h,
            "first_half_winner": (
                away_team if away_1h > home_1h
                else home_team if home_1h > away_1h
                else None
            ),
            "venue": ((comp.get("venue") or {}).get("fullName")),
        }

    # ---------------- convenience ----------------------------------------

    def to_json(self, games: list[dict], path: str | None = None) -> str:
        """Serialize a parsed game list to JSON, optionally to a file."""
        out = json.dumps(games, indent=2)
        if path:
            with open(path, "w") as f:
                f.write(out)
        return out


def _safe_int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    scraper = NFLGameScraper()
    if len(sys.argv) >= 3 and sys.argv[1] == "week":
        # nfl_game_scraper.py week 2025 17
        season = int(sys.argv[2])
        week = int(sys.argv[3]) if len(sys.argv) > 3 else 17
        games = scraper.fetch_week(season, week)
    elif len(sys.argv) == 2:
        # nfl_game_scraper.py 2025-12-28
        games = scraper.fetch_date(sys.argv[1])
    else:
        # No arg → default to most recent Sunday's games
        today = datetime.utcnow().date()
        days_back = (today.weekday() - 6) % 7  # 6 = Sunday
        last_sunday = today - timedelta(days=days_back)
        games = scraper.fetch_date(last_sunday.isoformat())

    print(f"Found {len(games)} NFL game(s).\n")
    for g in games:
        score = (
            f"{g['away_team']} {g['away_score']} @ {g['home_team']} {g['home_score']}"
            if g["completed"]
            else f"{g['away_team']} @ {g['home_team']} ({g['status']})"
        )
        print(f"  {g['date']}  {score}")
