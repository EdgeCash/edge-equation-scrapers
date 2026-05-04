# Run projection

## What it is

The model that predicts each team's expected runs in a game, taking team aggregates, recent form, opponent strength, pitching matchup, park, weather, and lineup into account. It feeds every market we publish (ML, RL, Totals, F5, F1, Team Totals) — they're all derived from the same projected runs.

## Why it matters

Every probability we publish — every Brier we measure, every CLV we capture, every conviction tier we assign — flows from this number. If the run projection drifts, every market drifts with it. The discipline of the formula matters more than any individual feature.

## The formula (in production)

Five stages, each with a clean reason for being there.

### Stage 1 — team-aggregate blend

For each team's offense (RS) and defense (RA):

```
team_blend = SEASON_WEIGHT × season_aggregate
           + RECENT_WEIGHT × last_10_games
           + OPPONENT_WEIGHT × opponent's_corresponding_aggregate
```

The season aggregate is itself shrunk via Bayesian smoothing:

```
shrunk_season = (team_runs + LEAGUE_AVG × SHRINKAGE_K) / (team_games + SHRINKAGE_K)
```

`SHRINKAGE_K = 15` ghost games at league average, so a team's first 10 games don't dominate their projection. Reduces early-season noise without erasing real form.

The season aggregate also has **exponential decay** applied — games closer to today contribute more than games a month ago, with a `DEFAULT_DECAY_HALF_LIFE_DAYS = 14` half-life. A game 14 days ago contributes half as much as today's game; a game 28 days ago, a quarter as much.

### Stage 2 — pitching adjustment (SP × BP)

The opposing team's pitching scales the projection:

```
away_runs *= SP_SHARE × home_sp_factor + BP_SHARE × home_bp_factor
home_runs *= SP_SHARE × away_sp_factor + BP_SHARE × away_bp_factor
```

`SP_SHARE = 5/9` and `BP_SHARE = 4/9` — matches the typical innings split (starters average 5-6 IP, bullpen covers 3-4). For First-5 markets, the split is `90% SP / 10% BP` since the SP carries almost the entire window.

See [`sp_factor.md`](./sp_factor.md) and [`bp_factor.md`](./bp_factor.md) for how those factors are computed.

### Stage 3 — park factor

```
away_runs *= park_factor(home_venue)
home_runs *= park_factor(home_venue)
```

Coors inflates run-scoring, Petco suppresses it, etc. Both teams' outputs are scaled equally — the venue affects both offenses identically. Park factors live in [`exporters/mlb/park_factors.py`](../../exporters/mlb/park_factors.py).

### Stage 4 — weather factor

```
weather_factor = 1.0 + temp_above_70F × 0.005
                # capped at ±10%
away_runs *= weather_factor
home_runs *= weather_factor
```

Temperature scales total run environment (hotter = ball carries farther, more runs). Domes and missing data both produce a neutral 1.0 factor. F5 totals get the weather effect at half magnitude (less of the game is played under it).

### Stage 5 — lineup factor

When today's posted lineup is missing star bats (vs. the team's typical lineup), the projection scales down:

```
away_runs *= lineup_factor(away_team, away_lineup)
home_runs *= lineup_factor(home_team, home_lineup)
```

Default 1.0 when no lineup is posted yet — no penalty for missing data. Computed from per-team aggregate hitter quality and the gap between today's posted starters and the season's typical lineup.

## Final outputs

The orchestrator returns a dict with these key fields per matchup:

| Field | Meaning |
|---|---|
| `away_runs_proj`, `home_runs_proj` | Full-game projected runs per team |
| `total_proj` | Sum of the two |
| `margin_proj` | Home minus away |
| `away_f5_proj`, `home_f5_proj` | First-5-innings projections |
| `away_win_prob`, `home_win_prob` | ML probabilities (computed from margin via logistic slope, see [`calibration.md`](./calibration.md)) |
| `nrfi_prob` | First-inning NRFI probability (separate sub-model) |

The market gate (see [`gate_logic.md`](./gate_logic.md)) decides which of these flow to the daily card.

## Constants in production

| Constant | Value | Why |
|---|---|---|
| `SEASON_WEIGHT` | `0.45` | Heaviest weight — full-season aggregates have the most data |
| `RECENT_WEIGHT` | `0.30` | Hot/cold streaks matter, but less than the long view |
| `OPPONENT_WEIGHT` | `0.25` | Symmetric: opp's run-allowing rate informs our run projection |
| `SHRINKAGE_K` | `15` | Ghost games at league average pulled into team aggregates |
| `DEFAULT_DECAY_HALF_LIFE_DAYS` | `14` | Recency-weighting on season-long aggregate |
| `SP_SHARE` / `BP_SHARE` | `5/9` / `4/9` | Full-game IP split |
| `F5_SP_SHARE` / `F5_BP_SHARE` | `0.90` / `0.10` | First-5 IP split (SP dominates) |
| `LEAGUE_AVG` (R/G) | calibrated season-by-season | Anchor for Bayesian shrinkage |

The standard deviations used to convert projections into probabilities (`TOTAL_SD`, `MARGIN_SD`, etc.) are *fitted from backtest residuals* every daily build, not hardcoded — see [`calibration.md`](./calibration.md).

## Implementation

| Component | Location |
|---|---|
| `ProjectionModel` class | [`exporters/mlb/projections.py`](../../exporters/mlb/projections.py) |
| `team_summary()` (season + recent aggregates) | same file |
| `_blend()` (the 45/30/25 weighted combine) | same file |
| `project_matchup()` (full pipeline) | same file |
| Park factors | [`exporters/mlb/park_factors.py`](../../exporters/mlb/park_factors.py) |
| Weather scraper | [`scrapers/mlb/weather_scraper.py`](../../scrapers/mlb/weather_scraper.py) |

## What this projection *doesn't* model

- **Umpire effects** — strike-zone variance affects K rate and walk rate. Top backlog item; manual data collection on the candidate list.
- **Catcher framing** — Statcast publishes per-catcher framing runs. Backlog.
- **Pitcher arsenal / pitch-mix** — sandbox-pending feature.
- **Wind direction** (only temperature is modeled). Manual data collection candidate.
- **Travel fatigue / rest-day effects** — not yet modeled.
- **Per-stat-type park factors** — current park factors are aggregate runs only; HR rate at Coors vs Petco isn't separately captured.

## BRAND_GUIDE link

The run projection is the foundation under every published probability. Serves *Facts. Not Feelings.* — every number on the daily card traces back to this formula.
