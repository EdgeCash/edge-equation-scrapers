# MLB Daily Spreadsheet Exporter

Builds a 6-tab spreadsheet of game-results bets (Moneyline, Run Line, Totals,
First 5, First Inning, Team Totals) with season-to-date backfill plus
projections for today's slate. Outputs are written to `public/data/mlb/` so a
Vercel-hosted frontend can serve them directly.

## Outputs

Written to `public/data/mlb/`:

| File | Purpose |
|------|---------|
| `mlb_daily.xlsx` | Multi-tab workbook (one tab per bet type). |
| `mlb_daily.json` | Structured payload for the frontend (all six tabs in one file). |
| `moneyline.csv` | Flat CSV for the Moneyline tab. `section` column = `projection` or `backfill`. |
| `run_line.csv` | Run Line tab. |
| `totals.csv` | Totals tab (lines 8.5 / 9.0 / 9.5). |
| `first_5.csv` | First 5 Innings tab. |
| `first_inning.csv` | First Inning (NRFI/YRFI) tab. |
| `team_totals.csv` | Team Totals tab (lines 3.5 / 4.5). Two rows per game (away + home). |

## Quick Start

```bash
pip install -r requirements.txt

# Build today's spreadsheet (no git push)
python -m exporters.mlb.daily_spreadsheet

# Build for a specific date
python -m exporters.mlb.daily_spreadsheet --date 2026-05-02

# Build and auto-commit + push (Vercel auto-deploys)
python -m exporters.mlb.daily_spreadsheet --push --branch main
```

## How Projections Are Built

The `ProjectionModel` aggregates every completed game in the season and
projects today's slate using a weighted blend:

| Component | Weight | What it captures |
|-----------|--------|------------------|
| Season pace | 0.45 | Team's full-season runs scored / allowed per game |
| Recent form | 0.30 | Same metrics but only over the last 10 games |
| Opponent | 0.25 | Opponent's defensive (or offensive) numbers |

For team A's projected runs vs B:

```
proj_A_runs = 0.45 * A_season_RS_pg
            + 0.30 * A_recent_RS_pg
            + 0.25 * B_season_RA_pg
```

Win probability is derived from projected margin via a logistic function
calibrated to MLB's typical run-differential to win-rate slope. Per-bet
outputs:

- **Moneyline:** `away_win_prob`, `home_win_prob`, `ml_pick`
- **Run Line:** `rl_fav`, `rl_margin_proj`, `rl_fav_covers_1_5`
- **Totals:** `total_proj` plus pick at 8.5 / 9.0 / 9.5
- **First 5:** `f5_total_proj`, `f5_pick`
- **First Inning:** `nrfi_prob`, `yrfi_prob`, `nrfi_pick` (independence assumed across teams)
- **Team Totals:** `team_total_proj` plus pick at 3.5 / 4.5

## Daily Cron

A simple cron line (e.g. on a small server or a Vercel scheduled task) that
refreshes the spreadsheet every morning:

```
30 13 * * *  cd /path/to/edge-equation-scrapers && \
             python -m exporters.mlb.daily_spreadsheet --push --branch main \
             >> /var/log/mlb_daily.log 2>&1
```

13:30 UTC ~ 8:30 AM ET: late enough that yesterday's slate is final, early
enough to project today's lines.

## Frontend Integration (Vercel)

Once Vercel redeploys after the push, the JSON is fetchable from your site
root:

```js
// Next.js example
const res = await fetch("/data/mlb/mlb_daily.json", { cache: "no-store" });
const data = await res.json();
data.tabs.moneyline.projections;  // today's ML projections
data.tabs.totals.backfill;         // season-to-date totals results
```

CSVs are also directly fetchable at e.g. `/data/mlb/totals.csv` if you'd
rather render them client-side with a CSV parser.
