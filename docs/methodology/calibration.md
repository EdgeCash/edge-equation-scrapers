# Calibration

## What it is

How we convert the model's projected run margin into a fair win probability. The projection model outputs `home_runs_proj − away_runs_proj` (a continuous number); the betting market needs `P(home wins)` (a probability in [0, 1]). The calibration layer is the bridge.

A 70% pick should win 70% of the time. If our 70% bucket actually wins 60%, we're systematically over-confident — and the calibration is wrong, regardless of whether the projection itself is good.

## Why it matters

Calibration directly drives Brier score (the metric we gate markets on) and edge calculation (the threshold we apply per pick). A miscalibrated model can be picking the right side and still failing the gate because its probability claims drift from reality.

## The current production formula — logistic slope

Projected margin → win probability via a single-parameter sigmoid:

```
win_prob_home = 1 / (1 + exp(-slope × margin_proj))
```

The `slope` is fit from backtest residuals: walk every game in the multi-season backfill, compute `(margin_proj, won_int_0_or_1)` pairs, then maximum-likelihood fit `slope` to minimize logistic loss.

Default value is `0.45` (`WIN_PROB_SLOPE`), but it gets overridden each morning by the value fitted from current backfill residuals — so the calibration adapts to recent games' patterns automatically.

## The validated alternative — isotonic regression

Per [PR #39](https://github.com/EdgeCash/edge-equation-scrapers/pull/39) and [PR #43](https://github.com/EdgeCash/edge-equation-scrapers/pull/43): the v1-ported isotonic regressor produces a monotonic step function from `(margin_proj, won)` pairs. More flexible than the single-slope sigmoid; can correct non-linear miscalibration.

K-fold validation result (5-fold time-series CV, 4-season backfill):

```
logistic Brier:  0.2473 ± 0.0006
isotonic Brier:  0.2466 ± 0.0005
delta:          +0.0006 ± 0.0003   (95% CI: [+0.0004, +0.0008])
```

Isotonic genuinely beats logistic. CI excludes zero. Modest absolute improvement (~0.24% relative Brier). **Not yet wired into the live projection** — currently the daily build emits both calibrations side-by-side in `backtest.json` (per PR #40), preserving evidence so we can flip the default after 2-3 weeks of real-data confirmation.

## ELO comparison (provocative finding worth noting)

Per [PR #41](https://github.com/EdgeCash/edge-equation-scrapers/pull/41) and [PR #43](https://github.com/EdgeCash/edge-equation-scrapers/pull/43): a stateless ELO model, knowing only the schedule of wins/losses (no SP, BP, weather, splits, lineup), produces ML probabilities that beat our current ProjectionModel:

```
current model Brier: 0.2474 ± 0.0003
ELO-only Brier:      0.2438 ± 0.0021
delta:              +0.0035 ± 0.0022   (95% CI: [+0.0016, +0.0055])
```

ELO wins by ~1.4% relative Brier. Plus, the 50/50 ensemble of ELO + current model gives the same Brier as ELO alone — meaning the current model contributes essentially zero on top of ELO for ML calibration specifically.

This doesn't mean ELO replaces the current model wholesale (ELO can't project totals, run line, F5, etc.). It does suggest:

- For ML calibration, we should consider using ELO directly
- For other markets, the current model's per-game features carry the value
- Every new ML feature we add should justify itself relative to "would ELO have been just as good?"

This is a finding, not yet a production change. Live picks use the current model's logistic-slope ML calibration.

## Probability-derivation for non-ML markets

For markets that aren't binary outcomes:

| Market | Distribution used | Constants |
|---|---|---|
| ML | Logistic on margin | `WIN_PROB_SLOPE = 0.45` (default), fit from residuals |
| Run line (-1.5/+1.5) | Same logistic, evaluated at `margin ± 1.5` | same |
| Totals (over/under) | Negative Binomial on total runs | `total_sd` fitted from residuals |
| First 5 totals | Negative Binomial on F5 total | `f5_total_sd` fitted from residuals |
| First 5 ML | Same logistic, on F5 margin | `f5_margin_sd` fitted |
| Team Totals | Negative Binomial on team's runs | `team_total_sd` fitted |
| First Inning (NRFI/YRFI) | Empirical league F1 score-rate baseline (`LEAGUE_F1_SCORE_RATE = 0.27`) modified by SP factor + lineup | per-team F1 aggregates |

The `*_sd` constants are fit from `BacktestEngine._calibration()` every morning by computing `pstdev(actual - projected)` over the multi-season residuals, clamped to `[0.5, 2× default]` to prevent pathological values.

## Constants in production

| Constant | Default | Override behavior |
|---|---|---|
| `WIN_PROB_SLOPE` | `0.45` | Overridden by `_fit_logistic_slope()` from backtest residuals each morning |
| `TOTAL_SD` | `3.0` | Overridden by `pstdev()` of total-runs residuals |
| `TEAM_TOTAL_SD` | `2.2` | Overridden by team-total residuals |
| `MARGIN_SD` | `3.5` | Overridden by margin residuals |
| `F5_TOTAL_SD` | `2.2` | Overridden by F5 total residuals |
| `F5_MARGIN_SD` | `2.2` | Overridden by F5 margin residuals |
| `LEAGUE_F1_SCORE_RATE` | `0.27` | Empirical F1-inning-scoring rate; drives NRFI/YRFI baseline |

Per-game calibration constants flow into `ProjectionModel(calibration=…)` via the daily build. The `calibration.json` published to `public/data/mlb/` records the fitted values for every daily build.

## Implementation

| Component | Location |
|---|---|
| `_fit_logistic_slope()` | [`exporters/mlb/backtest.py`](../../exporters/mlb/backtest.py) |
| `BacktestEngine._calibration()` (orchestrator) | same file |
| `IsotonicRegressor` (validated alternative) | [`exporters/mlb/isotonic.py`](../../exporters/mlb/isotonic.py) |
| `EloCalculator` (validated baseline) | [`exporters/mlb/elo.py`](../../exporters/mlb/elo.py) |
| `time_series_split()` (k-fold validator) | [`exporters/mlb/cv.py`](../../exporters/mlb/cv.py) |
| Negative Binomial helpers | [`exporters/mlb/projections.py`](../../exporters/mlb/projections.py) |
| Reliability diagram on the website | [`web/components/CalibrationChart.tsx`](../../web/components/CalibrationChart.tsx) |

## Validation discipline

Every alternative we consider goes through the same gate:

1. **Smoke test** the math against textbook expectations (e.g. equal ELO ratings → 0.5 probability)
2. **K-fold time-series CV** on the multi-season backfill — single random splits OVERSTATE results (we caught this with both isotonic and ELO)
3. **CI must exclude zero** before declaring a winner
4. **Live evidence accumulation** — when an alternative validates statistically, we emit it alongside the current method in `backtest.json` for 2-3 weeks before flipping the default

This is the discipline yesterday's ELO + isotonic ports established as the v1-port template.

## BRAND_GUIDE link

Calibration is what makes our Brier numbers honest. *"Facts. Not Feelings."* requires probabilities that reflect actual outcomes — the calibration layer is where that promise lives or dies.
