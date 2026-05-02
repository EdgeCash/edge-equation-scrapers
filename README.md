# Edge Equation

> **Facts. Not Feelings.** — Transparent sports analytics with honest modeling, rigorous testing, and public learning.

Edge Equation is the data, model, and publishing pipeline behind [edge-equation.vercel.app](https://edge-equation.vercel.app). MLB is live; NFL and NCAAF are in the offseason build queue. Every play we publish carries a model probability, a Kelly unit size, an edge calculation against the live market, and a closing-line snapshot. We grade ourselves in public.

The single source of truth for brand, product rules, and operational standards is **[`docs/BRAND_GUIDE.md`](docs/BRAND_GUIDE.md)**. Read it first — every architectural decision in this repo defers to it.

## What's live

| Sport | Pipeline | Web | Status |
|-------|----------|-----|--------|
| MLB | ✅ Daily build, NegBin model, market gating, CLV tracking, auto-grading | ✅ Daily card + track record + methodology pages | Production |
| NFL | 🟡 Game scraper landed; odds + projection model June–August | — | Off-season build |
| NCAAF | 🟡 Game scraper landed; same trajectory as NFL | — | Off-season build |
| NHL / Soccer | ⚪ Legacy stubs from earlier prototypes | — | Not in v5.0 scope |

## Quick start

```bash
# Install deps (Python 3.11+)
pip install -r requirements.txt

# Optional: free tier from https://the-odds-api.com — without this,
# the pipeline falls back to a DraftKings public scraper.
export ODDS_API_KEY=...

# Run today's full MLB pipeline
python run_mlb_daily.py

# Or pass through any flag the underlying exporter supports
python run_mlb_daily.py --date 2026-05-02 --no-odds
python run_mlb_daily.py --push --branch main
```

Outputs land in `public/data/mlb/` — `mlb_daily.json`, `todays_card.csv`, `backtest.json`, `picks_log.json`, plus per-tab CSVs and a multi-tab XLSX. The Vercel site auto-redeploys on every push.

## Architecture map

```
edge-equation-scrapers/
├── docs/BRAND_GUIDE.md       Single source of truth (locked v0.2)
├── run_mlb_daily.py          Top-level pipeline entry point
│
├── scrapers/                 Per-sport data ingestion
│   ├── mlb/                  Games, odds, pitchers, bullpen, weather, lineups, settle
│   ├── nfl/                  Game scraper (rest of pipeline coming)
│   ├── ncaaf/                Game scraper (subclasses NFL)
│   └── nhl/, soccer/         Legacy from earlier prototypes
│
├── exporters/                Output assembly
│   └── mlb/                  Projection model, Kelly sizing, backtest, CLV tracker,
│                             daily spreadsheet builder, closing snapshot CLI
│
├── models/                   Reserved for sport-agnostic model work
├── global_utils/             Cross-sport helpers (Odds API quota log, etc.)
│
├── web/                      Production Next.js v5.0 site
│   └── app/, components/     Chalkboard aesthetic, conviction tiers, daily card
│
├── public/data/mlb/          Daily-build outputs (auto-generated; gitignored content)
│
└── .github/workflows/        Daily cron (11 AM ET) + closing-line snapshot cron
```

Each major folder has a `README.md` with details. Start with the brand guide, then drop into the folder you need.

## How the model works (one paragraph)

For each game we project per-team run scoring as a weighted blend of season pace, recent form (with 14-day exponential decay), and opponent context — with Bayesian shrinkage, park factor, weather factor, opposing starting pitcher (FIP-blended with last-3-starts), opposing bullpen, and day-of lineup scratches stacked on top. Run totals are modeled Negative-Binomial (over-dispersed counts) rather than Poisson. The half-Kelly bet size is capped at 5% per play and 6% across same-game correlated bets. A pick only ships on the daily card if its market clears the rolling-backtest gate (≥+1% ROI **and** Brier <0.246 over 200+ bets). Some days that means publishing zero plays — that's a feature, not a bug. Full methodology: [`/methodology`](https://edge-equation.vercel.app/methodology) on the live site or [`exporters/mlb/README.md`](exporters/mlb/README.md).

## Daily automation

Two GitHub Actions cron jobs ship the live experience without human input:

- **`mlb-daily.yml`** — 15:00 UTC (11:00 AM ET during DST) — runs `run_mlb_daily.py`, commits outputs, triggers Vercel redeploy.
- **`mlb-closing-lines.yml`** — every 30 min through game windows — re-snaps live odds for unsettled picks, computes CLV.

`ODDS_API_KEY` lives in repo secrets. Smart-gating in the closing-snapshot job keeps Odds API burn around 5–8 calls/day on a typical slate.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Briefly: feature branch → PR → merge to `main`. Reference the BRAND_GUIDE section your work advances. Don't add markets or bet types that haven't earned their way through the gate.

## License + responsibility

Edge Equation is sports analytics, not financial or gambling advice. Past performance does not guarantee future results. Models can and will be wrong. Never wager more than you can afford to lose. US problem-gambling helpline: **1-800-522-4700**.
