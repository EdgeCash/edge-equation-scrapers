"""
WNBA Game Results Scraper
=========================
Pulls WNBA game schedule + results from ESPN's free scoreboard JSON.
Inherits the NFL scraper wholesale — basketball's 4-quarter structure
matches American football's parsing model exactly (Q1, Q2, Q3, Q4
linescores; first half = Q1+Q2). Only the ESPN endpoint URL differs.

Volume note: WNBA regular season runs ~mid-May through ~mid-September
with 12 teams playing 40 games each. Total ~240 games per regular
season + ~25 playoff games = ~265 games. Date-range based since the
schedule isn't strictly weekly.

Usage:
    scraper = WNBAGameScraper()
    games = scraper.fetch_date("2024-08-15")
    games = scraper.fetch_range("2024-05-01", "2024-09-30")
"""

from __future__ import annotations

import sys
from datetime import datetime

from scrapers.nfl.nfl_game_scraper import NFLGameScraper

WNBA_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball"
    "/wnba/scoreboard"
)

# WNBA has fewer games per night than NFL (~3-6 vs ~13-16) so the
# ESPN default page size is fine, but we set a higher limit anyway
# for safety on weekly date-range pulls.
DEFAULT_LIMIT = 100


class WNBAGameScraper(NFLGameScraper):
    """WNBA game scraper. Inherits NFL parsing wholesale — only the
    ESPN endpoint and a default limit override differ."""

    def __init__(self):
        super().__init__()
        self.base_url = WNBA_SCOREBOARD_URL

    def _fetch_and_parse(self, params: dict) -> list[dict]:
        """Inject our default limit on every call. Doesn't touch the
        NFL scraper's parser since 4-quarter basketball linescores
        slot directly into the NFL parsing model."""
        merged = {"limit": DEFAULT_LIMIT, **(params or {})}
        return super()._fetch_and_parse(merged)


if __name__ == "__main__":
    scraper = WNBAGameScraper()
    if len(sys.argv) == 2:
        games = scraper.fetch_date(sys.argv[1])
    else:
        today = datetime.utcnow().date().isoformat()
        games = scraper.fetch_date(today)
    print(f"Found {len(games)} WNBA game(s).\n")
    for g in games:
        score = (
            f"{g['away_team']} {g['away_score']} @ {g['home_team']} {g['home_score']}"
            if g["completed"]
            else f"{g['away_team']} @ {g['home_team']} ({g['status']})"
        )
        print(f"  {g['date']}  {score}")
