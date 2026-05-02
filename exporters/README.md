# exporters/

Output assembly and the entry-point pipelines that chain scrapers → projection model → market gate → file outputs.

## Layout

| Subdirectory | Purpose |
|--------------|---------|
| [`mlb/`](mlb/README.md) | Daily MLB pipeline. Projection model, Kelly sizing, backtest, CLV tracker, daily spreadsheet builder, closing snapshot CLI, auto-grader. Plus 🟣 `player_props_experimental.py` — sandboxed prop projections that write to `data/experimental/mlb-props/` for offline auditing only. |

## Convention

Each sport's exporter:

- Owns its **projection model** (for now — see [`models/README.md`](../models/README.md) for the migration plan)
- Builds the **daily spreadsheet** (multi-tab xlsx + per-tab CSVs + structured JSON)
- Writes outputs to `public/data/<sport>/` so the website can serve them as static files
- Has a CLI entry point that's also callable as a Python module: `python -m exporters.<sport>.daily_spreadsheet`

## How outputs reach the live site

```
exporters/mlb/daily_spreadsheet.py
  ↓ writes
public/data/mlb/*.json + *.csv + *.xlsx
  ↓ committed by GitHub Actions
git push to main
  ↓ webhook
Vercel rebuilds web/ (which copies public/data/ into its own public/)
  ↓
edge-equation.vercel.app reflects fresh data
```

The mechanism is the same for every sport once we add more — just point the daily cron at the new sport's exporter.

## Top-level entry point

For convenience, the repo root has [`run_mlb_daily.py`](../run_mlb_daily.py) which wraps `python -m exporters.mlb.daily_spreadsheet` with a friendlier name. Runs the same code path; same flags. Add `run_<sport>_daily.py` siblings as new sports come online.
