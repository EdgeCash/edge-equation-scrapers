"""
NCAAF Game Results Scraper
==========================
Same ESPN scoreboard JSON shape as the NFL scraper, just a different
sport URL plus two required query params:

  - groups=80 — restricts to FBS (Division I-A). Without this, ESPN's
    public scoreboard returns a curated "featured" subset (top-25 +
    headlining games) that misses the long tail of G5 / mid-major
    matchups, which is precisely where the softest lines and the real
    edge potential sit.
  - limit=300 — the default page size is ~50, which silently truncates
    on big Saturdays (60-80 FBS games). 300 is comfortably above any
    realistic week's volume.

Volume note: a typical college Saturday has 50–80 FBS games (vs
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

# Always-on params for FBS coverage. Without these the public ESPN
# endpoint serves a curated subset that drops most G5 / mid-major
# games — the data we most care about.
DEFAULT_PARAMS = {"groups": 80, "limit": 300}


class NCAAFGameScraper(NFLGameScraper):
    """College football game scraper. Inherits NFL parsing wholesale —
    only the ESPN endpoint and the required FBS-coverage params differ."""

    def __init__(self):
        super().__init__()
        self.base_url = NCAAF_SCOREBOARD_URL

    def _fetch_and_parse(self, params: dict) -> list[dict]:
        """Inject groups=80 + limit=300 on every call so we always pull
        the full FBS slate, not the curated 'featured' default."""
        merged = {**DEFAULT_PARAMS, **(params or {})}
        return super()._fetch_and_parse(merged)

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
