"""
NBA Game Results Scraper
========================
Pulls NBA game schedule + results from ESPN's free scoreboard JSON.
Inherits NFL parsing wholesale — basketball's 4-quarter structure
matches the NFL parser model exactly. Only the ESPN endpoint URL
differs.

Volume note: NBA regular season runs ~mid-October through mid-April
with 30 teams playing 82 games each = ~1,230 regular-season games.
Plus playoffs (~85 games). Date-range based since the schedule isn't
strictly weekly.

Strategic context: NBA is one of the SHARPEST betting markets in
sports. We harvest data here for diversification + cross-sport
infrastructure reuse, not because we expect a real edge against the
books on NBA-specific markets. If something useful emerges from a
backtest, great; if not, the data foundation has value either way.

Usage:
    scraper = NBAGameScraper()
    games = scraper.fetch_date("2024-12-25")
    games = scraper.fetch_range("2024-10-01", "2024-10-31")
"""

from __future__ import annotations

import sys
from datetime import datetime

from scrapers.nfl.nfl_game_scraper import NFLGameScraper

NBA_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball"
    "/nba/scoreboard"
)

# NBA has ~10-15 games per night peak, ~3-7 typical. ESPN's default
# limit (~50) handles single dates fine but we set higher for weekly
# range pulls.
DEFAULT_LIMIT = 200


class NBAGameScraper(NFLGameScraper):
    """NBA game scraper. Inherits NFL parsing wholesale — only the
    ESPN endpoint and a default limit override differ."""

    def __init__(self):
        super().__init__()
        self.base_url = NBA_SCOREBOARD_URL

    def _fetch_and_parse(self, params: dict) -> list[dict]:
        merged = {"limit": DEFAULT_LIMIT, **(params or {})}
        return super()._fetch_and_parse(merged)


if __name__ == "__main__":
    scraper = NBAGameScraper()
    if len(sys.argv) == 2:
        games = scraper.fetch_date(sys.argv[1])
    else:
        today = datetime.utcnow().date().isoformat()
        games = scraper.fetch_date(today)
    print(f"Found {len(games)} NBA game(s).\n")
    for g in games:
        score = (
            f"{g['away_team']} {g['away_score']} @ {g['home_team']} {g['home_score']}"
            if g["completed"]
            else f"{g['away_team']} @ {g['home_team']} ({g['status']})"
        )
        print(f"  {g['date']}  {score}")
