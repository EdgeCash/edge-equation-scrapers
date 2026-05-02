# public/

Static outputs served directly by Vercel. **Auto-generated. Don't hand-edit.**

## Layout

```
public/
└── data/
    └── mlb/                   ← daily-build outputs
        ├── mlb_daily.json     ← structured payload (consumed by web/)
        ├── todays_card.csv    ← headline shortlist
        ├── backtest.json      ← per-market ROI + Brier + daily P&L
        ├── picks_log.json     ← persistent log with grading + CLV
        ├── lines.json         ← multi-book odds snapshot
        ├── odds_debug.json    ← eyeball view with vig-free probs
        ├── calibration.json   ← fitted SDs / ML slope from backtest
        ├── quota_log.json     ← Odds API burn tracking
        ├── *.csv              ← per-tab flat exports
        └── mlb_daily.xlsx     ← multi-tab workbook
```

## How it gets there

The 11 AM ET cron (`.github/workflows/mlb-daily.yml`) runs `run_mlb_daily.py --push`, which:

1. Generates all the files above in `public/data/mlb/`
2. Commits them to `main`
3. Pushes — which triggers Vercel rebuild → site reflects fresh data within ~1-2 minutes

## What the website does with them

The `web/` Next.js app fetches `/data/mlb/mlb_daily.json` and `/data/mlb/picks_log.json` on the daily-card and track-record pages. The `web/scripts/copy-data.js` build step mirrors this directory into `web/public/data/` during Vercel deploy.

## Local dev

If you want to test the website against fresh data locally, run the pipeline first:

```bash
python run_mlb_daily.py
cd web && npm run dev      # copy-data runs automatically
```

## Why files here aren't gitignored

Output files are committed to `main` deliberately so:
- Vercel can serve them without a backend
- The full history of every published card is auditable on GitHub
- Backtest evolution over time is visible by walking commits

The `web/public/data/` mirror IS gitignored (see `web/.gitignore`) since it's a build artifact, not a source-of-truth.
