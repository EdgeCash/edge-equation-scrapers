# data/backfill/

Multi-season historical data, pulled in bulk for offline model fine-tuning. **Not used by the live daily pipeline** — production code reads only the current season.

## Layout

```
data/backfill/
└── mlb/
    └── <season>/
        ├── games.json                Season-long results (cheap; ~30 API calls)
        └── boxscores/
            └── <game_pk>.json        Per-game lineup + per-player stat lines
                                      (heavy; one file per game, ~2,500/season)
```

## How to populate

```bash
# Fast — just game results for last 4 completed seasons (~2 minutes total)
python run_mlb_backfill.py

# Full — games + per-game boxscores for specified seasons (~45 min/season)
python run_mlb_backfill.py --seasons 2022,2023,2024 --with-boxscores

# Range syntax also works
python run_mlb_backfill.py --seasons 2021-2024 --with-boxscores
```

Re-running is **idempotent**. Already-cached games and boxscores are skipped, so you can interrupt long boxscore harvests and resume.

## What it's used for (offline only)

| Use case | What it enables |
|----------|-----------------|
| **Calibration refit** | Re-run BacktestEngine across multiple seasons → larger sample for SD / ML-slope fitting → less seasonal noise in calibration values |
| **Multi-season Brier validation** | Confirm that the model's per-market Brier scores hold up across years, not just the current season |
| **Prop backtest grading** | The boxscores contain the actual per-player stat lines we need to grade prop projections against historical games |
| **Form-decay tuning** | Test different decay half-lives (currently 14 days) against years of data to find the one that maximizes out-of-sample Brier |
| **Model A/B** | Compare projection-model variants against the same historical sample |

## Why this isn't auto-fetched

- One-time bulk operation. After the initial pull, the data sits unchanged unless we explicitly re-fetch.
- Boxscore harvest takes ~45 min per season at the polite default request interval. Not cron-friendly.
- Live daily build doesn't need it; pulling every day would waste API time and add no signal.

## Why it's not under `public/`

This data is internal model-development infrastructure, not user-facing. Mirrors the same boundary as [`data/experimental/`](../experimental/): anything inside `data/` is sandboxed; anything inside `public/data/` is what the website serves.

## Polite scraping

The MLB Stats API (`statsapi.mlb.com`) is unmetered as far as we know, but bulk harvests should still throttle. Default `--request-interval` is 1.0 seconds. Lower at your own risk; we don't want to be the project that gets the endpoint locked down.
