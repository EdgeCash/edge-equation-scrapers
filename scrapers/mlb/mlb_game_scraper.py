"""
MLB Game Results Scraper
========================
Fetches game results from the MLB Stats API and computes betting-relevant
metrics: Moneyline, Run Line, First 5 Innings, First Inning (NRFI/YRFI),
Over/Under Totals, and Team Totals.

Data source: https://statsapi.mlb.com (free, no auth required)

Usage:
    python mlb_game_scraper.py                  # Yesterday's games
    python mlb_game_scraper.py 2026-05-01       # Specific date
    python mlb_game_scraper.py 2026-04-01 2026-04-30  # Date range
"""

import requests
import json
import sys
from datetime import datetime, timedelta

BASE_URL = "https://statsapi.mlb.com/api/v1"

TEAM_MAP = {
    108: "LAA", 109: "AZ", 110: "BAL", 111: "BOS", 112: "CHC",
    113: "CIN", 114: "CLE", 115: "COL", 116: "DET", 117: "HOU",
    118: "KC", 119: "LAD", 120: "WSH", 121: "NYM", 133: "ATH",
    134: "PIT", 135: "SD", 136: "SEA", 137: "SF", 138: "STL",
    139: "TB", 140: "TEX", 141: "TOR", 142: "MIN", 143: "PHI",
    144: "ATL", 145: "CWS", 146: "MIA", 147: "NYY", 158: "MIL",
}


class MLBGameScraper:
    """Scrapes MLB game results and computes bet-grading metrics."""

    def __init__(self):
        self.base_url = BASE_URL

    def fetch_schedule(self, start_date, end_date=None):
        """
        Fetch games with linescore data for a date or date range.
        Returns list of dicts, one per completed game with all metrics.
        """
        if end_date is None:
            end_date = start_date

        url = (
            f"{self.base_url}/schedule"
            f"?sportId=1&startDate={start_date}&endDate={end_date}"
            f"&hydrate=linescore"
            f"&fields=dates,date,games,gamePk,status,detailedState,"
            f"teams,away,home,team,id,name,score,isWinner,"
            f"linescore,innings,num,away,home,runs,hits,errors"
        )

        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for date_obj in data.get("dates", []):
            game_date = date_obj["date"]
            for game in date_obj.get("games", []):
                if game.get("status", {}).get("detailedState") != "Final":
                    continue
                parsed = self._parse_game(game, game_date)
                if parsed:
                    results.append(parsed)
        return results

    def _parse_game(self, game, game_date):
        """Parse a single game into betting-relevant metrics."""
        try:
            away_info = game["teams"]["away"]
            home_info = game["teams"]["home"]

            away_id = away_info["team"]["id"]
            home_id = home_info["team"]["id"]
            away_team = TEAM_MAP.get(away_id, str(away_id))
            home_team = TEAM_MAP.get(home_id, str(home_id))

            away_score = away_info.get("score", 0)
            home_score = home_info.get("score", 0)
            total_runs = away_score + home_score

            innings = game.get("linescore", {}).get("innings", [])

            # First inning runs
            inn1_away = self._inning_runs(innings, 1, "away")
            inn1_home = self._inning_runs(innings, 1, "home")
            first_inning_runs = inn1_away + inn1_home

            # First 5 innings
            f5_away = sum(self._inning_runs(innings, i, "away") for i in range(1, 6))
            f5_home = sum(self._inning_runs(innings, i, "home") for i in range(1, 6))

            return {
                "date": game_date,
                "game_pk": game.get("gamePk"),
                "away_team": away_team,
                "home_team": home_team,
                "away_score": away_score,
                "home_score": home_score,
                "total_runs": total_runs,
                "ml_winner": away_team if away_score > home_score else home_team,
                "rl_margin": abs(away_score - home_score),
                "rl_favorite_covered": abs(away_score - home_score) >= 2,
                "f5_away": f5_away,
                "f5_home": f5_home,
                "f5_winner": (
                    away_team if f5_away > f5_home
                    else home_team if f5_home > f5_away
                    else "PUSH"
                ),
                "f1_away": inn1_away,
                "f1_home": inn1_home,
                "nrfi": first_inning_runs == 0,
                "total": total_runs,
                "away_total": away_score,
                "home_total": home_score,
                "innings": [
                    {"inning": inn.get("num"),
                     "away": inn.get("away", {}).get("runs", 0),
                     "home": inn.get("home", {}).get("runs", 0)}
                    for inn in innings
                ],
            }
        except (KeyError, TypeError):
            return None

    @staticmethod
    def _inning_runs(innings, num, side):
        """Get runs for a specific inning number and side."""
        for inn in innings:
            if inn.get("num") == num:
                return inn.get(side, {}).get("runs", 0)
        return 0

    def yesterday(self):
        """Fetch yesterday's completed games."""
        dt = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        return self.fetch_schedule(dt)

    def season_to_date(self, season=2026):
        """Fetch all games from Opening Day through yesterday."""
        start = f"{season}-03-20"
        end = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        return self.fetch_schedule(start, end)

    def to_json(self, games, path=None):
        """Serialize game list to JSON. Optionally write to file."""
        output = json.dumps(games, indent=2)
        if path:
            with open(path, "w") as f:
                f.write(output)
        return output


if __name__ == "__main__":
    scraper = MLBGameScraper()

    if len(sys.argv) == 3:
        games = scraper.fetch_schedule(sys.argv[1], sys.argv[2])
    elif len(sys.argv) == 2:
        games = scraper.fetch_schedule(sys.argv[1])
    else:
        games = scraper.yesterday()

    print(f"Found {len(games)} completed games")
    for g in games:
        nrfi_tag = "NRFI" if g["nrfi"] else "YRFI"
        print(
            f"  {g['date']}  {g['away_team']} {g['away_score']} @ "
            f"{g['home_team']} {g['home_score']}  |  "
            f"ML: {g['ml_winner']}  |  F5: {g['f5_away']}-{g['f5_home']}  |  "
            f"{nrfi_tag}  |  Total: {g['total']}"
        )
