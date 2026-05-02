# MLB Scrapers - Edge Equation

MLB game results, player props, and pick-settling engine powered by the **MLB Stats API** (statsapi.mlb.com). No API key needed - fully free and public.

## Scripts

| File | Purpose |
|------|--------|
| mlb_game_scraper.py | Fetch game results with full linescore breakdowns. Computes ML, Run Line, F5, NRFI/YRFI, O/U, and Team Total metrics. |
| mlb_player_scraper.py | Fetch player game logs and grade prop results (K lines for pitchers, Hits/TB/HR/SB for batters). |
| mlb_settle_engine.py | Grade published Edge Equation picks against actual results for the Track Record page. |
| mlb_odds_scraper.py | Pull live ML / Run Line / Totals prices from The Odds API (with DraftKings fallback). |
| mlb_pitcher_scraper.py | Pull today's probable starting pitchers + their season stats and compute a quality factor used by the projection model. |
| mlb_player_props_scraper.py | 🟣 EXPERIMENTAL — slate-driven player stats fetcher (pitcher Ks/IP/BAA, batter AVG/SLG/AB) for the sandboxed prop projections. Not used by the live daily card. |
| mlb_backfill_scraper.py | Multi-season bulk harvester. Pulls historical games (cheap) + per-game boxscores (heavy, opt-in via `--with-boxscores`) into `data/backfill/mlb/<season>/`. One-time bulk operation; not on a cron. Used for offline calibration refits and prop backtest grading. |

## Quick Start

```bash
pip install requests

# Fetch yesterday's game results
python mlb_game_scraper.py

# Fetch a specific date
python mlb_game_scraper.py 2026-05-01

# Fetch a date range
python mlb_game_scraper.py 2026-04-01 2026-04-30

# Fetch all tracked player props
python mlb_player_scraper.py

# Settle yesterday's picks
python mlb_settle_engine.py --picks picks.json --output settled.json
```

## Tracked Players

### Pitchers (12)
Skenes, Skubal, Wheeler, Sale, Webb, Glasnow, Yamamoto, Valdez, Cease, Cole, Burnes, Strider

### Batters (11)
Ohtani, Judge, Tatis Jr., Soto, Witt Jr., Henderson, Betts, Freeman, De La Cruz, Acuna Jr., Seager

## Prop Lines Graded

| Type | Lines |
|------|------|
| Pitcher Ks | O4.5, O5.5, O6.5, O7.5 |
| Batter Hits | O0.5, O1.5 |
| Batter Total Bases | O1.5, O2.5 |
| Batter HR | O0.5 |
| Batter SB | O0.5 |

## Data Source

All data from the public MLB Stats API. No authentication required.
