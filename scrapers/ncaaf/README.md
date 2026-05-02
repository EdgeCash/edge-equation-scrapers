# NCAAF Scrapers — Edge Equation v5.0

Same shape as `scrapers/nfl/` — ESPN's college-football scoreboard JSON has identical structure, just a different URL. `NCAAFGameScraper` subclasses `NFLGameScraper` and overrides only the endpoint.

## What's here

| File | Purpose |
|------|---------|
| `ncaaf_game_scraper.py` | Fetch + parse FBS games from ESPN. Inherits NFL parsing wholesale. |

## Quick start

```bash
python -m scrapers.ncaaf.ncaaf_game_scraper                    # last Saturday's games
python -m scrapers.ncaaf.ncaaf_game_scraper 2025-11-29
python -m scrapers.ncaaf.ncaaf_game_scraper week 2025 14
```

## Volume note

College Saturday slates run 50–100 FBS games (vs ~14–16 NFL games per week). If you want to harvest a full season:

```python
scraper = NCAAFGameScraper()
games = scraper.fetch_season(2025)  # ~16 weeks × ~70 games = ~1100 games
```

Each weekly call is a single request, so a season harvest is 16 ESPN hits regardless of game count.

## Roadmap

Same trajectory as NFL — schedule + results first (done), odds + projection model in late summer, daily-card publishing once a market clears the BRAND_GUIDE gate.

NCAAF has more variance and bigger talent gaps than NFL, which means:
- Larger spreads (book lines often 30+ points)
- More frequent push at non-standard hooks
- Backdoor cover dynamics more pronounced
- Per-team sample sizes are smaller (12-13 games regular season)

The team-aggregate decay we built for MLB will need a longer half-life (probably 3-4 weeks not 14 days) since recent form means less when the schedule strength varies wildly week-to-week.
