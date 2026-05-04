# Gate logic

## What it is

The set of rules that decide which markets and which individual picks ship to the daily card. Two layers: a **market gate** (does this entire bet type — ML, RL, etc. — earn a spot today?) and **per-pick filters** (does this specific game's projection clear the edge threshold?). Plus a portfolio cap to size correlated bets sanely.

## Why it matters

Discipline. The brand promise — *"everything visible has been measured"* — depends on these rules being applied consistently and visibly. The gate is what keeps unprofitable markets off the daily card while we keep building them in the background, and what keeps a single high-edge slate from over-staking via correlated bets on the same game.

## The rules (in order of application)

### Rule 1 — market gate (BRAND_GUIDE Product Rules)

A bet type is eligible to ship today **only if its rolling backtest** clears all three:

```
backtest_bets         >= 200       # sample size floor
backtest_roi_pct      >= +1.0      # +1% ROI in units (flat 1u at -110)
backtest_brier         < 0.246     # Brier score
```

If any one of these fails, the bet type is dropped from the daily card entirely (but stays visible in its own per-market tab and in the spreadsheet — transparency, not erasure).

The backtest used is the **multi-season rolling backtest** computed every morning by the daily build. It walks every game in the loaded backfill, projects using only prior data, and grades against actuals.

### Rule 2 — pick must have a real market price

```
if pick.market_odds_dec is None:
    # No book covered this market for this game today.
    # Synthesize -110 if you want, but DON'T ship it as a play.
    drop()
```

We do not publish picks at synthetic prices. If the markets we follow don't price this side, we don't ship it.

### Rule 3 — per-market edge threshold

Each bet type has a per-market threshold the pick must clear:

| Market | Threshold |
|---|---|
| `moneyline` | `≥4.0%` |
| `run_line` | `≥3.0%` |
| `totals` | `≥2.5%` |
| `first_5` | `≥2.5%` |
| `first_inning` | `≥4.0%` |
| `team_totals` | `≥3.0%` |

`edge_pct = model_prob × 100 - implied_prob_from_market_odds`. Higher thresholds for noisier or thinner markets (ML moves fastest; F1/NRFI is the most variance-prone bucket per game).

A picks-eligible market with edge below threshold lands in the FADE / SKIP list, not on the daily card. Visible, but flagged as "model didn't clear the bar."

### Rule 4 — top-N filtering

Sort surviving picks by `edge_pct` descending, take the top `DEFAULT_TOP_N = 10`. The brand guide's *3-8 high-conviction plays per day* is the typical outcome; some days fewer survive, some days more — capping at 10 prevents us from over-shipping on a particularly bullish slate.

### Rule 5 — portfolio cap per game

Same-game bets are correlated (an OVER total + a fav ML + a RL bet are all juiced by the same offensive eruption). Full-Kelly across all of them over-stakes the slate. We cap the *sum* of half-Kelly% across one matchup at:

```
DEFAULT_PORTFOLIO_CAP_PER_GAME = 6.0   # % of bankroll
```

When a game's combined Kelly exceeds the cap, all picks on that game are scaled down proportionally to fit. The reduced Kelly% is reflected in the published `kelly_pct` and `kelly_advice` (e.g. a 2u play might become 1u after correlation scaling).

## Status output (visible on every spreadsheet row)

Per [PR #38](https://github.com/EdgeCash/edge-equation-scrapers/pull/38), every row in every per-market spreadsheet carries:

- **`status`**: `"PLAY"` or `"PASS"`
- **`status_reason`**: empty for PLAYs; for PASSes, one of:
  - `"Market gated off (Brier 0.2476)"` — Rule 1 failure
  - `"No market price available"` — Rule 2 failure
  - `"Edge +X.XX% below +Y.YY% threshold"` — Rule 3 failure

Top-N (Rule 4) and portfolio cap (Rule 5) are not failures per se — they're size adjustments. A pick that fails Top-N still appears in its per-market tab; just not on the headline card.

## Constants in production

| Constant | Value | Source |
|---|---|---|
| `DEFAULT_MIN_GATE_BETS` | `200` | BRAND_GUIDE Product Rules |
| `DEFAULT_MIN_GATE_ROI` | `1.0` (i.e. +1.0%) | BRAND_GUIDE Product Rules |
| `DEFAULT_MAX_GATE_BRIER` | `0.246` | BRAND_GUIDE Product Rules |
| `DEFAULT_MIN_EDGE_PCT` | `3.0%` (fallback if market not in table) | Per-market table overrides |
| `DEFAULT_TOP_N` | `10` | Caps a particularly bullish slate |
| `DEFAULT_PORTFOLIO_CAP_PER_GAME` | `6.0%` | Half-Kelly correlation cap |

The market-gate constants are deliberately the same numbers as the brand guide — flipping any of them is a brand-guide update, not a code change. The per-market edge thresholds are tuneable (and visible in `DEFAULT_EDGE_THRESHOLDS_BY_MARKET`).

## Implementation

| Component | Location |
|---|---|
| `_market_gate()` | [`exporters/mlb/daily_spreadsheet.py`](../../exporters/mlb/daily_spreadsheet.py) |
| `_inject_status_columns()` | same file |
| `_build_todays_card()` | same file |
| Portfolio-cap logic | inside `_build_todays_card` |

## What gating is *not*

- **Not a permanent ban.** A market that fails the gate today can earn it back tomorrow with a single new winning week. The gate re-evaluates every morning.
- **Not erasure.** Failing markets stay visible on the website (per-market tabs + the /downloads page) and in the Excel workbook. Transparency includes "here's what didn't clear today and why."
- **Not an ML-style threshold-tuning game.** The brand-guide constants (200 bets, +1% ROI, Brier <0.246) are *product rules*, not hyperparameters. They get debated in updates to BRAND_GUIDE.md, not silently tweaked in code.

## BRAND_GUIDE link

This is the codification of [BRAND_GUIDE.md → Product Rules → Market gating](../BRAND_GUIDE.md). Any deviation here is a brand-guide bug.
