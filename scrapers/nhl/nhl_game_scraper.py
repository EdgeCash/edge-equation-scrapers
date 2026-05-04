"""
NHL Game Results Scraper
========================
Pulls NHL game schedule + results from ESPN's free scoreboard JSON
(`site.api.espn.com`). Mirrors the NFL/NCAAF/MLB scraper shape so
downstream model code can reuse the same factor-stacking patterns
once we have enough seasons of NHL data to calibrate against.

Key bet-relevant fields per game:
    - moneyline winner
    - puck line margin (home - away, signed)
    - total goals
    - 1st period total + winner (NHL analog of MLB's NRFI/YRFI)
    - per-period scores (period totals + props later)
    - went_to_ot flag (regular-season ties resolve via OT/SO; this
      tells you whether to treat the game as 60-min or 65+ min)

Data source: ESPN public scoreboard JSON. No auth.

Usage:
    scraper = NHLGameScraper()
    games = scraper.fetch_date("2024-12-15")
    games = scraper.fetch_range("2024-10-01", "2024-10-31")
"""

from __future__ import annotations

import json
import sys
from datetime import datetime

import requests

SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard"
)

# ESPN's default page size is ~50, fine for a single date but
# truncates on weekly date ranges (~15 games/day × 7 days = ~105 max).
# 200 is comfortably above any realistic week's volume.
DEFAULT_LIMIT = 200


class NHLGameScraper:
    """Pulls completed and upcoming NHL games into a normalized shape."""

    def __init__(self):
        self.base_url = SCOREBOARD_URL

    def fetch_date(self, date: str) -> list[dict]:
        """Return all NHL games on the given date (YYYY-MM-DD)."""
        date_compact = date.replace("-", "")
        return self._fetch_and_parse({"dates": date_compact})

    def fetch_range(self, start_date: str, end_date: str) -> list[dict]:
        """Compact date-range form (ESPN accepts YYYYMMDD-YYYYMMDD)."""
        start = start_date.replace("-", "")
        end = end_date.replace("-", "")
        return self._fetch_and_parse({"dates": f"{start}-{end}"})

    def _fetch_and_parse(self, params: dict) -> list[dict]:
        merged = {"limit": DEFAULT_LIMIT, **params}
        try:
            resp = requests.get(self.base_url, params=merged, timeout=30)
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

        # Per-period scores. Hockey has 3 periods; OT/SO add extra
        # linescore entries (period 4 = OT, period 5 = SO). We pad to
        # 3 for index safety but preserve all entries so callers can
        # detect OT.
        away_periods = [_safe_int(p.get("value")) for p in away.get("linescores") or []]
        home_periods = [_safe_int(p.get("value")) for p in home.get("linescores") or []]
        while len(away_periods) < 3:
            away_periods.append(0)
        while len(home_periods) < 3:
            home_periods.append(0)
        went_to_ot = len(away_periods) > 3 or len(home_periods) > 3

        away_p1 = away_periods[0]
        home_p1 = home_periods[0]
        first_period_total = away_p1 + home_p1
        first_period_winner = (
            away_team if away_p1 > home_p1
            else home_team if home_p1 > away_p1
            else None
        )

        margin = home_score - away_score
        ml_winner = (
            away_team if margin < 0
            else home_team if margin > 0
            else None
        )

        raw_date = event.get("date") or comp.get("date") or ""
        date_str = raw_date[:10] if raw_date else None

        return {
            "date": date_str,
            "game_id": str(event.get("id")),
            "season": (event.get("season") or {}).get("year"),
            "season_type": (event.get("season") or {}).get("type"),
            "status": status_type.get("name"),
            "completed": completed,
            "away_team": away_team,
            "home_team": home_team,
            "away_score": away_score,
            "home_score": home_score,
            "total_goals": away_score + home_score,
            "ml_winner": ml_winner,
            "margin": margin,                   # signed home - away
            "puck_line_margin": abs(margin),
            "went_to_ot": went_to_ot,
            "away_periods": away_periods,       # [P1, P2, P3, (OT, SO)]
            "home_periods": home_periods,
            "away_p1": away_p1,
            "home_p1": home_p1,
            "first_period_total": first_period_total,
            "first_period_winner": first_period_winner,
            "venue": ((comp.get("venue") or {}).get("fullName")),
        }


def _safe_int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    scraper = NHLGameScraper()
    if len(sys.argv) == 2:
        games = scraper.fetch_date(sys.argv[1])
    else:
        today = datetime.utcnow().date().isoformat()
        games = scraper.fetch_date(today)
    print(f"Found {len(games)} NHL game(s).\n")
    for g in games:
        score = (
            f"{g['away_team']} {g['away_score']} @ {g['home_team']} {g['home_score']}"
            f"{' OT/SO' if g.get('went_to_ot') else ''}"
            if g["completed"]
            else f"{g['away_team']} @ {g['home_team']} ({g['status']})"
        )
        print(f"  {g['date']}  {score}")
