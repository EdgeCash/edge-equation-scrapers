"""
NCAAF Game Results Scraper
==========================
Same ESPN scoreboard JSON shape as the NFL scraper, just a different
sport URL. Subclasses NFLGameScraper and overrides the endpoint —
keeps parsing logic in one place.

Volume note: a typical college Saturday has 50–100 FBS games (vs
~14–16 NFL games per week). The fetch_date / fetch_range helpers
batch fine; fetch_season iterates ~15 weeks of regular season +
bowl/playoff weeks if requested.

Usage:
    scraper = NCAAFGameScraper()
    games = scraper.fetch_date("2025-11-29")
    games = scraper.fetch_week(season=2025, week=14)
"""

from __future__ import annotations

from scrapers.nfl.nfl_game_scraper import NFLGameScraper

NCAAF_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/football"
    "/college-football/scoreboard"
)
NCAAF_REGULAR_WEEKS = 16  # 15-16 weeks regular + bowls + playoff


class NCAAFGameScraper(NFLGameScraper):
    """College football game scraper. Inherits NFL parsing wholesale —
    only the ESPN endpoint differs."""

    def __init__(self):
        super().__init__()
        self.base_url = NCAAF_SCOREBOARD_URL

    def fetch_season(
        self,
        season: int,
        season_type: int = 2,
        weeks: int = NCAAF_REGULAR_WEEKS,
    ) -> list[dict]:
        """Override default week count for the longer college season."""
        return super().fetch_season(season, season_type=season_type, weeks=weeks)


if __name__ == "__main__":
    import sys
    scraper = NCAAFGameScraper()
    if len(sys.argv) == 2:
        games = scraper.fetch_date(sys.argv[1])
    elif len(sys.argv) >= 3 and sys.argv[1] == "week":
        season = int(sys.argv[2])
        week = int(sys.argv[3]) if len(sys.argv) > 3 else 14
        games = scraper.fetch_week(season, week)
    else:
        from datetime import datetime, timedelta
        # Default to most recent Saturday
        today = datetime.utcnow().date()
        days_back = (today.weekday() - 5) % 7
        last_sat = today - timedelta(days=days_back)
        games = scraper.fetch_date(last_sat.isoformat())

    print(f"Found {len(games)} NCAAF game(s).\n")
    for g in games:
        score = (
            f"{g['away_team']} {g['away_score']} @ {g['home_team']} {g['home_score']}"
            if g["completed"]
            else f"{g['away_team']} @ {g['home_team']} ({g['status']})"
        )
        print(f"  {g['date']}  {score}")
