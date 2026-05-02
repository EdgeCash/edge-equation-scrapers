# NFL Scrapers — Edge Equation v5.0

Foundation for the NFL data pipeline. Mirrors the structure of `scrapers/mlb/` so the projection-model patterns we built for MLB (factor stacking, NegBin, calibration, market gating) can be ported once we have enough seasons of data to fit on.

## What's here

| File | Purpose |
|------|---------|
| `nfl_game_scraper.py` | ESPN scoreboard JSON → normalized game dicts (date, score, margin, 1H total, quarter scores). |

## What's coming (not yet built)

| Component | Notes |
|-----------|-------|
| Odds scraper | Wire `MLBOddsScraper`'s pattern with sport_key `americanfootball_nfl`. |
| Team aggregates | NFL has weekly cadence (not daily), so per-week sample is small — shrinkage prior matters more. |
| Player / QB stats | Required for sharper SP-equivalent (QB matters more in NFL than SP in MLB; rest days, injury status matter). |
| Weather | Outdoor stadiums only; same Open-Meteo path. |
| Lineups / inactives | Inactives report posted ~90 min pre-kick; contains scratched stars. |
| Projection model | Factor stack: team form (decay) + QB factor + injury adjustments + park (turf vs grass marginal) + weather. |
| Bet types | Spread, Moneyline, Total, 1H Spread/Total, Team Totals. No NFL equivalent of NRFI/F5 — different markets entirely. |

## Quick start

```bash
python -m scrapers.nfl.nfl_game_scraper                       # last Sunday's games
python -m scrapers.nfl.nfl_game_scraper 2025-12-28             # specific date
python -m scrapers.nfl.nfl_game_scraper week 2025 17           # season + week
```

Output is a parsed list of game dicts with the same field naming style as the MLB scraper, suitable for direct piping into a future `NFLProjectionModel`.

## Data source

ESPN public scoreboard endpoint:
```
https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard
  ?dates=YYYYMMDD                  # single date
  ?dates=YYYY&seasontype=2&week=N  # by week
  ?dates=YYYYMMDD-YYYYMMDD         # range
```

No auth, no documented quota. Generally reliable but not contractually so — if reliability becomes an issue, fall back to NFL.com's stats API or scrape Pro Football Reference.

## Roadmap (per BRAND_GUIDE Dev Priorities)

- **Now (May 2026)**: schedule + results scraper ✅
- **June**: odds scraper + bet-type extraction; team aggregates from prior season(s)
- **July**: QB factor + injury / inactives integration; projection model v1
- **August**: market-gate validation against prior-season backtest; daily-card publishing
- **September (kickoff)**: live model, NFL plays on the daily card

Same discipline applies as MLB: a market only ships when its 200+ bet rolling backtest shows ≥+1% ROI AND Brier < 0.246.
