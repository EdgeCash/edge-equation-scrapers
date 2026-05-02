# data/backfill/

Multi-season historical data, pulled in bulk for offline model fine-tuning. **Not used by the live daily pipeline** — production code reads only the current season.

## Layout

```
data/backfill/
└── mlb/
    └── <season>/
        ├── games.json                Season-long results (cheap; ~30 API calls)
        └── boxscores.tar.gz          Per-game lineup + per-player stats
                                      (~50 MB compressed per season,
                                       ~2,500 boxscores inside)
```

The compacted tarball is the persistent form. During harvest the
scraper writes loose `boxscores/<game_pk>.json` files; once the season
is complete the orchestrator (`--compact`) bundles them into the
tarball and removes the loose copies. ~5x size reduction.

## How to populate

### Option A — One-click GitHub Action (recommended)

1. Go to the repo's **Actions** tab → **MLB Backfill (manual)**
2. Click **Run workflow**
3. Inputs:
   - `seasons` — leave blank for the last 4 completed seasons, or specify (e.g. `2022,2023,2024` or `2022-2024`)
   - `with_boxscores` — check for the full prop-grading dataset (~45 min per season)
   - `request_interval` — leave at `1.0` (polite); `0.3` is safe for short bursts
4. **Run workflow** — it'll churn for up to a few hours, then commit `data/backfill/` and push to `main`.

The workflow auto-compacts boxscores before commit so the repo doesn't bloat.

### Option B — Local

```bash
# Fast — just game results for last 4 completed seasons (~2 minutes total)
python run_mlb_backfill.py

# Full — games + per-game boxscores, then compact to per-season tarballs
python run_mlb_backfill.py --seasons 2022-2024 --with-boxscores --compact

# Lower request interval at your own risk (default 1.0s is polite)
python run_mlb_backfill.py --with-boxscores --compact --request-interval 0.3
```

Re-running is **idempotent**. Already-cached games and boxscores are skipped, so you can interrupt long boxscore harvests and resume.

## Reading the compacted tarballs

```python
from scrapers.mlb.mlb_backfill_scraper import MLBBackfillScraper
from pathlib import Path

# Inspect what's inside a season's archive
import tarfile
with tarfile.open("data/backfill/mlb/2024/boxscores.tar.gz") as tar:
    print(f"{len(tar.getnames())} games in archive")

# Pull a single boxscore back out
box = MLBBackfillScraper.read_boxscore_from_tarball(
    Path("data/backfill/mlb/2024/boxscores.tar.gz"),
    game_pk=716351,
)
```

Or from the shell:

```bash
tar -tzf data/backfill/mlb/2024/boxscores.tar.gz | head        # list
tar -xzOf data/backfill/mlb/2024/boxscores.tar.gz 716351.json  # extract one
```

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
