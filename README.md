# Edge Equation Scrapers

This project consists of various web scrapers for different sports to gather data and provide insights.

## Structure

- `scrapers/` — per-sport data ingestion modules.
  - `scrapers/mlb/` — MLB pipeline: games, odds, probable pitchers, bullpen, weather, lineups, settle engine.
  - `scrapers/nfl/` — NFL game scraper (foundation; full pipeline mid-summer).
  - `scrapers/ncaaf/` — NCAAF game scraper (subclasses NFL; same trajectory).
  - `scrapers/nhl/`, `scrapers/soccer/` — legacy game scrapers from earlier prototypes.
- `exporters/mlb/` — daily MLB spreadsheet (Today's Card + 6 bet tabs + Backtest), CLV tracker, projection model, backtest engine, auto-grader. Writes `public/data/mlb/`.
- `web/` — production Next.js v5.0 site (chalkboard aesthetic). Deployed to Vercel with `web/` as Root Directory; `npm run build` mirrors data files into the build automatically. See `web/README.md`.
- `docs/BRAND_GUIDE.md` — single source of truth for brand identity, conviction tiers, market gating, and operational standards. Locked at v0.2.
- `.github/workflows/` — daily build cron (11:00 AM ET) + closing-line snapshot cron (every 30 min through game windows).
- `public/data/` — static outputs served by Vercel; updated by the daily cron.

## Requirements

To install the required packages, use: 

```bash
pip install -r requirements.txt
```

## Usage

```bash
# MLB: full daily build (backfill, projections, odds, gating, output files)
python -m exporters.mlb.daily_spreadsheet --push --branch main

# MLB: closing-line snapshot (called by the closing-lines cron)
python -m exporters.mlb.closing_snapshot --push

# NFL: pull a date or week of games
python -m scrapers.nfl.nfl_game_scraper 2025-12-28
python -m scrapers.nfl.nfl_game_scraper week 2025 17

# NCAAF: same shape as NFL
python -m scrapers.ncaaf.ncaaf_game_scraper 2025-11-29
```

## Roadmap (BRAND_GUIDE Dev Priorities)

- ✅ MLB: NegBin projections, run-line inversion, CLV tracking, market gating, auto-grading
- ✅ Site: v5.0 chalkboard design, conviction tiers, live daily card + track record
- 🟡 NFL: schedule/results scraper landed; odds + projection model coming June–August
- 🟡 NCAAF: same trajectory as NFL
- ⏸️ Player props: gated on game-level model proving consistent +CLV first