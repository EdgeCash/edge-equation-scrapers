# Closing-line value (CLV)

## What it is

The percentage-point difference between the price we took and the price the market closed at. Positive CLV means we beat the closing line — we got a sharper price than the consensus when the bet finally closed. Negative CLV means we paid worse than the close.

## Why it matters

CLV is the single most reliable truth-teller in sports betting. Win-rate noise is huge over short windows (a 55% bettor can easily go 4-12 over 16 picks); CLV converges much faster because every pick contributes signal regardless of outcome. Long-run profitability tracks CLV more strongly than raw W/L.

A model losing to the close is bleeding EV regardless of short-term wins. A model consistently beating the close by 1-2% is grinding out edge that will eventually show up as ROI, even through extended losing streaks.

This is why the brand guide lists *"CLV-first mindset"* as a Core Value and *"CLV snapshot recorded on every published pick before first pitch"* as Operational Standard #2.

## The formula

```
pick_implied_prob   = 1 / pick_decimal_odds
closing_implied_prob = 1 / closing_decimal_odds
clv_pct              = (closing_implied_prob - pick_implied_prob) × 100
```

If we took +150 (1/2.5 = 40% implied) and the line closed at +130 (1/2.3 = 43.5% implied), CLV is `(0.435 - 0.40) × 100 = +3.5%`. The market moved toward our pick; we got a sharper price than the close.

## The pipeline

CLV requires capturing the price at TWO moments in time, plus grading the result later.

### Step 1 — record the pick (morning daily build, ~11 AM ET)

`record_picks()` is called as part of every morning daily build. For every play that lands on the daily card, it logs:

- The pick metadata (matchup, bet type, pick side)
- The decimal odds + American odds + book at time of pick
- The model's probability + implied edge%
- A timestamp + game_pk + game_time

Stored in `public/data/mlb/picks_log.json`. Append-only and idempotent on `pick_id` — re-running the morning build doesn't duplicate.

### Step 2 — snap the closing price (every 30 minutes during game windows)

The `mlb-closing-lines.yml` cron runs every 30 minutes from 17:00–23:30 UTC plus 00:00–04:00 UTC. For every unsettled pick whose game is within 90 minutes of first pitch, it:

1. Re-fetches market odds via The Odds API
2. Looks up the same bet (by spec — same side, same line, same market) in the new odds
3. If found, records `closing_price_dec`, `closing_price_american`, `closing_book`, `closing_recorded_at`
4. Computes `clv_pct` using the formula above

The "smart gate" — only fetching odds when there are unsettled picks within the window — saves ~70-80% of closing-snapshot API calls on the average MLB day.

### Step 3 — grade the pick (next morning's daily build)

When the next morning's build runs, `grade_resolved_picks()` walks the picks log against the now-completed games. For each pick whose game has finished, it:

1. Looks up the actual outcome (ML winner, total, run-line cover, etc.)
2. Resolves the pick to `WIN`, `LOSS`, or `PUSH`
3. Computes `units` based on the pick's price (positive on wins, -1u on losses, 0 on pushes)
4. Sets `graded_at` timestamp

Idempotent: picks that already have a `result` are skipped.

### Step 4 — publish summary

`save_summary()` writes `public/data/mlb/clv_summary.json` after every closing-snapshot run AND after every morning daily build. The summary aggregates:

- Overall mean / median / positive-share CLV
- Per-bet-type breakdown
- Full-history record (W-L-P, units, ROI, mean CLV)
- 30-day rolling window (the brand-guide-mandated public stat)

The website's `/track-record` page consumes this file directly.

## Coverage caveat

Not every pick gets a closing snapshot. The matching logic (`find_closing_price`) requires:

- The same bet TYPE (ML, RL, totals)
- The same SIDE (e.g. OVER vs UNDER)
- The same LINE (e.g. -1.5 spread, total of 9.0)

If the line moves between morning and close (e.g. opens at 9.5, closes at 9.0), the pick's specific line isn't in the closing-odds payload and we can't snap it. This affects Totals most often. Currently a known limitation; the cleanest fix is matching on side + closest-line within ±0.5 instead of exact line — backlogged.

## Constants and decisions

| Choice | Value | Why |
|---|---|---|
| Snapshot window | 30 minutes pre-first-pitch through end-of-slate | Captures the closing line near first pitch; preserves it through the game. |
| Smart-gate window | 90 minutes pre-first-pitch | Only burn an Odds API call if there's a pick to snap. |
| Cron schedule | every 30 min, 17-23 UTC + 00-04 UTC | Covers all MLB game start times across timezones. |
| `pick_id` format | `{date}|{matchup}|{bet_type}|{pick}` | Deterministic + idempotent across morning rebuilds. |

## Implementation

| Component | Location |
|---|---|
| `ClvTracker` class | [`exporters/mlb/clv_tracker.py`](../../exporters/mlb/clv_tracker.py) |
| `parse_spec()`, `find_closing_price()` | same file |
| `compute_clv()` | same file |
| `record_closing_lines()` | same file |
| `grade_resolved_picks()` | same file |
| Closing-snapshot runner | [`exporters/mlb/closing_snapshot.py`](../../exporters/mlb/closing_snapshot.py) |
| Closing-snapshot cron | [`.github/workflows/mlb-closing-lines.yml`](../../.github/workflows/mlb-closing-lines.yml) |
| Daily-build wiring | [`exporters/mlb/daily_spreadsheet.py`](../../exporters/mlb/daily_spreadsheet.py) — calls `tracker.record_picks()`, `tracker.grade_resolved_picks()`, `tracker.save_summary()` |

## What this *doesn't* model

- **Line-shopping CLV** — we measure CLV against the closing price at the same book where we placed the bet. A "best-line CLV" metric (closing across all books) would be more honest about whether you could have actually realized the edge with line shopping.
- **Vig-adjusted CLV** — the formula above uses raw implied probabilities including the book's vig. A truly fair CLV would strip vig from both prices first. Common practice is to leave it in for simplicity; we can revisit if it ever matters for a decision.

## BRAND_GUIDE link

Direct implementation of:
- *Core Value: CLV-first mindset*
- *Operational Standard #2: CLV snapshot recorded on every published pick before first pitch*
- *Operational Standard #4: Public 30-day rolling CLV updated daily, visible to anyone* (consumed by `/track-record`)
