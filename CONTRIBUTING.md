# Contributing to Edge Equation

The single source of truth for tone, product rules, and operational standards is **[`docs/BRAND_GUIDE.md`](docs/BRAND_GUIDE.md)**. Read it first. Every PR should advance a section in that document — and if your work changes one of those rules, update the brand guide *before* the code that implements the change.

## Workflow

1. **Branch.** Create a feature branch off `main`. Naming: `claude/<short-description>` for AI-driven work, anything-clear for human work.
2. **Commit.** Small, focused commits. Use a descriptive title (one line, ~70 chars) and a body that explains *why*, not just *what*. Reference the BRAND_GUIDE section your work advances when relevant (e.g. "Implements BRAND_GUIDE Operational Standards #4").
3. **PR to `main`.** Include a summary, list of files touched, and a test plan. The repo's existing PR descriptions are good templates.
4. **Merge.** Squash or merge — either is fine. Once merged, the daily cron picks up the change automatically on the next 11 AM ET run.

## Brand discipline (non-negotiable)

- **Don't bypass the market gate.** A market only ships on the daily card after 200+ rolling backtest bets show ≥+1% ROI **and** Brier <0.246. Adding markets that don't clear the bar — even temporarily — breaks the entire promise of the brand.
- **Empty cards are correct.** "No play is the play" days are part of the system, not a bug to work around.
- **CLV is the truth-teller.** Prefer changes that improve CLV (especially the 30-day rolling number) over changes that improve W/L hit rate alone. CLV correlates with long-run profitability; W/L correlates with luck.
- **Versioned changes.** When you alter projection math, commit message should call it out so we can A/B against prior model behavior in the backtest.

## Code standards

- **Python**: 3.11+. Type hints encouraged; no enforcement framework. Avoid scipy/pandas in core paths — stdlib + `requests` keeps cold-start lean. Heavy deps (numpy, etc.) are fine inside isolated experimental modules.
- **TypeScript**: matches the Next.js 15 App Router defaults in `web/`. Tailwind for styling. Server components where possible.
- **Tests**: smoke-test new logic before committing — even quick `python3 << EOF` blocks are fine. The goal is "I confirmed this doesn't break."
- **Comments**: explain *why*, not *what*. The brand guide has the philosophy; code comments fill in the local context.

## Adding a new sport

When NFL / NCAAF / NHL / etc. graduate from offseason scaffolding to live publishing:

1. Game scraper lives at `scrapers/<sport>/`. Same shape as `scrapers/mlb/`.
2. Cross-sport helpers (Odds API quota log, etc.) go in `global_utils/`. Sport-specific factors (team mappings, projection layers) stay in the sport's directory.
3. Output assembly lives at `exporters/<sport>/`. Outputs land in `public/data/<sport>/`.
4. Web routes mirror the sport: `/<sport>-card`, `/track-record/<sport>`, etc. (Today's Card stays single-page, just multi-sport once we have more than one).
5. Add a daily cron workflow under `.github/workflows/<sport>-daily.yml`.
6. **Don't publish picks until the gate is cleared.** Off-season publishing is fine for backtest/methodology pages, but the daily card is reserved for proven markets.

## Quick checklist before opening a PR

- [ ] Code runs locally (`python run_mlb_daily.py --no-odds` works without crashing)
- [ ] No regressions in the smoke-tests you ran
- [ ] If you changed projection math: a one-line note in the commit body about expected impact on Brier
- [ ] If you changed brand-relevant rules (tier thresholds, gate criteria, operational SLAs): you've also updated `docs/BRAND_GUIDE.md` in the same PR
- [ ] Folder READMEs updated if you added new top-level files

## Bet responsibly

This project is sports analytics, not financial or gambling advice. Past performance does not guarantee future results. US problem-gambling helpline: **1-800-522-4700**.
