# MLB Daily Spreadsheet Exporter

Builds a 6-tab spreadsheet of game-results bets (Moneyline, Run Line, Totals,
First 5, First Inning, Team Totals) with season-to-date backfill plus
projections for today's slate. Outputs are written to `public/data/mlb/` so a
Vercel-hosted frontend can serve them directly.

## Outputs

Written to `public/data/mlb/`:

| File | Purpose |
|------|---------|
| `mlb_daily.xlsx` | Multi-tab workbook — Today's Card · 6 bet tabs · Backtest. |
| `mlb_daily.json` | Structured payload for the frontend (all tabs + odds + backtest). |
| `lines.json` | Raw market odds snapshot (all sportsbooks, normalized). |
| `backtest.json` | Standalone backtest payload (overall + per-bet-type + daily P&L + bet log). |
| `todays_card.csv` | Headline shortlist of today's actionable picks ranked by Kelly. |
| `moneyline.csv` | Moneyline tab. `section` column = `projection` or `backfill`. |
| `run_line.csv` | Run Line tab. |
| `totals.csv` | Totals tab (lines 8.5 / 9.0 / 9.5). |
| `first_5.csv` | First 5 Innings tab. |
| `first_inning.csv` | First Inning (NRFI/YRFI) tab. |
| `team_totals.csv` | Team Totals tab (lines 3.5 / 4.5). Two rows per game (away + home). |
| `backtest.csv` | Backtest tab — overall + per-bet-type summary, plus daily P&L. |

## Quick Start

```bash
pip install -r requirements.txt

# Optional: free key from https://the-odds-api.com (500 req/month)
export ODDS_API_KEY=...

# Build today's spreadsheet (no git push)
python -m exporters.mlb.daily_spreadsheet

# Build for a specific date
python -m exporters.mlb.daily_spreadsheet --date 2026-05-02

# Skip the odds fetch entirely (Kelly falls back to -110 default)
python -m exporters.mlb.daily_spreadsheet --no-odds

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
- **Run Line:** `rl_fav`, `rl_margin_proj`, `rl_cover_prob`, `rl_fav_covers_1_5`
- **Totals:** `total_proj` plus pick at 8.5 / 9.0 / 9.5
- **First 5:** `f5_total_proj`, `f5_pick`, `f5_win_prob`
- **First Inning:** `nrfi_prob`, `yrfi_prob`, `nrfi_pick` (independence assumed across teams)
- **Team Totals:** `team_total_proj` plus pick at 3.5 / 4.5

### Kelly sizing

Every projection row carries a Kelly recommendation:

| Column | Meaning |
|--------|---------|
| `model_prob` | Probability the model assigns to the recommended pick. |
| `fair_odds_dec` | Decimal odds implied by `model_prob` (i.e. `1 / model_prob`). Compare against the market line. |
| `market_odds_dec` / `market_odds_american` | Best price available across books for this exact pick (or `null` if no market data). |
| `book` | Sportsbook offering that best price. |
| `kelly_pct` | Recommended bet size as a percentage of bankroll. **Half-Kelly, capped at 5%.** Computed with `market_odds_dec` when available, otherwise the -110 default. |
| `kelly_advice` | Categorical tier: `PASS` / `0.5u` / `1u` / `2u` / `3u`. |
| `kelly_line` | (Totals & Team Totals only) Which line + side the Kelly recommendation refers to (e.g. `OVER 8.5`). |

When no market price is found for a given bet (e.g. F5/F1/team totals are
rarely on the free Odds API tier), Kelly falls back to a default price of
**-110 (decimal 1.909)**. ML/Run Line/Totals get live multi-book prices when
`ODDS_API_KEY` is set or the DraftKings fallback succeeds.

The full Kelly fraction is `(b*p - q) / b` where `b = decimal_odds - 1`,
`p = model_prob`, `q = 1 - p`. We halve it (Kelly is well-known to be too
aggressive when probability estimates are noisy) and cap at 5% of bankroll
to keep one bad day from wrecking the bankroll.

For non-binary markets (totals, run-line, team totals, F5) the model produces
a point estimate; we derive a probability via a normal-CDF transform using
calibrated standard deviations:

| Market | SD assumed |
|--------|-----------|
| Game total runs | 3.0 |
| Team total runs | 2.2 |
| Game run margin | 3.5 |
| First 5 total | 2.2 |
| First 5 margin | 2.2 |

## Odds Sources

Live market prices are fetched in this order:

1. **The Odds API** (`https://the-odds-api.com`) — free tier 500 req/month,
   covers DK, FanDuel, MGM, Caesars, etc. Set `ODDS_API_KEY` (env var) or
   pass `--odds-api-key`. **Recommended.**
2. **DraftKings public sportsbook JSON** — undocumented endpoint on
   `sportsbook-nash.draftkings.com`, no auth, single book, fragile.
3. **Empty / fallback** — if both fail, Kelly sizing uses the -110 default.

For each market, the BEST available price (highest decimal odds) across
books is what feeds Kelly sizing — i.e. line shopping. The full multi-book
snapshot is persisted to `public/data/mlb/lines.json` for transparency.

## Daily Automation

The repo ships with a GitHub Actions workflow at
`.github/workflows/mlb-daily.yml` that runs the build every morning at
13:30 UTC (≈ 8:30 AM ET — late enough that yesterday's slate is final on
statsapi.mlb.com, early enough to publish today's projections before first
pitch). It commits the new files to `main`, which triggers an automatic
Vercel redeploy.

To enable it:

1. Push this repo to GitHub.
2. In the repo settings → Secrets and variables → Actions, add a secret
   named `ODDS_API_KEY` with your free key from the-odds-api.com (skip
   this and the workflow will fall back to the DraftKings scraper).
3. The workflow runs automatically on the cron schedule. You can also
   trigger it manually from the Actions tab (workflow_dispatch) and
   optionally pass a target date.

For self-hosted cron:

```
30 13 * * *  cd /path/to/edge-equation-scrapers && \
             ODDS_API_KEY=xxx \
             python -m exporters.mlb.daily_spreadsheet --push --branch main \
             >> /var/log/mlb_daily.log 2>&1
```

## Backtest

Every daily run includes a model backtest in the `Backtest` tab and in
`backtest.json`. The engine walks the season game-by-game and projects
each game using ONLY data available before it (no look-ahead), grading
the model's pick against the actual outcome. Bets are flat 1u at -110.

Headline numbers exposed:

- Per-bet-type hit rate, units P&L, ROI %
- Overall record across all bet types
- Daily cumulative P&L curve
- Full bet log (date, matchup, bet_type, pick, prob, result, units)

Use it as a sanity check: bet types with a long-run negative units P&L
are the model's blind spots and may warrant tighter Kelly sizing — or
sitting them out entirely.

## Today's Card

The first tab is a cross-tab roll-up of every actionable pick from the
six bet tabs, ranked by half-Kelly fraction descending. PASS picks (no
edge / negative EV) drop into a separate section so you can see what the
model considered and rejected.

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
