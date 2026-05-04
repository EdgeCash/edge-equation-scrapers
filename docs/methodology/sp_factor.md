# Starting-pitcher (SP) factor

## What it is

A multiplicative adjustment applied to the OPPOSING team's projected runs based on the starting pitcher's quality. A great SP scales opp-runs *down*; a bad one scales them *up*. The factor is bounded so a single dominant or disastrous SP can't break the projection.

## Why it matters

The starting pitcher has the largest single-game influence of any player in baseball — they typically face 18-25 batters out of ~38. A good SP factor is the single most important adjustment in the game-level projection, which is why we layer three sources of SP signal (season aggregate + recent form + prior-season expected outcomes) rather than relying on any one.

## The formula (in production)

The shipped value is computed in three stages, each with a clear purpose.

### Stage 1 — season FIP-based factor (Bayesian shrinkage)

```
weighted_FIP = (FIP × IP + LEAGUE_FIP × IP_PRIOR) / (IP + IP_PRIOR)
season_factor = clamp(weighted_FIP / LEAGUE_FIP, FACTOR_MIN, FACTOR_MAX)
```

`IP_PRIOR` adds 50 ghost innings of league-average performance, so a pitcher with 6 dominant innings doesn't project as the next Bob Gibson. As IP grows, the prior's pull weakens and the actual FIP dominates. Below `MIN_IP_FOR_SIGNAL` (5 IP), the factor falls back to 1.0 (no adjustment).

### Stage 2 — blend with last-3-starts FIP

```
blended_FIP = (1 - RECENT_BLEND_WEIGHT) × season_FIP + RECENT_BLEND_WEIGHT × recent_FIP
factor = clamp(blended_FIP / LEAGUE_FIP, FACTOR_MIN, FACTOR_MAX)
```

`RECENT_BLEND_WEIGHT = 0.30` — a 70/30 blend of season vs. last-3-starts. This lets hot/cold streaks pull the factor without letting a single bad outing override months of evidence.

### Stage 3 — blend with prior-season xwOBA prior (when available)

```
xwoba_factor = clamp(prior_season_xwOBA / LEAGUE_XWOBA, FACTOR_MIN, FACTOR_MAX)
final_factor = clamp(
    (1 - XWOBA_BLEND_WEIGHT) × stage_2_factor
    + XWOBA_BLEND_WEIGHT × xwoba_factor,
    FACTOR_MIN, FACTOR_MAX
)
```

`XWOBA_BLEND_WEIGHT = 0.30` — Statcast expected wOBA from the prior season acts as a stabilizing prior. Strips luck (BABIP variance, HR/FB) from the assessment and pulls toward true talent. When prior-season xwOBA isn't available (rookie SP, insufficient prior PAs), the stage-2 factor is used unchanged.

## Constants in production

| Constant | Value | Why this number |
|---|---|---|
| `LEAGUE_FIP` | `4.20` | MLB-wide modern era. Calibrated so league-average FIP ≈ league-average ERA. |
| `FIP_CONSTANT` | `3.10` | Additive constant in the FIP formula `(13×HR + 3×(BB+HBP) - 2×K)/IP + cFIP`. |
| `IP_PRIOR` | `50.0` | Ghost innings of league-average performance for shrinkage. |
| `MIN_IP_FOR_SIGNAL` | `5.0` | Below this many IP, factor = 1.0. |
| `FACTOR_MIN` / `FACTOR_MAX` | `0.70` / `1.30` | Outer bounds — even an extreme outlier can't move opp-runs by more than ±30%. |
| `RECENT_BLEND_WEIGHT` | `0.30` | Weight on last-3-starts FIP in the blended factor. |
| `LEAGUE_XWOBA` | `0.310` | League-average expected wOBA against from Statcast leaderboards. |
| `XWOBA_BLEND_WEIGHT` | `0.30` | Weight on prior-season xwOBA factor in the final blend. |

## Implementation

| Component | Location |
|---|---|
| `compute_fip()` | [`scrapers/mlb/mlb_pitcher_scraper.py`](../../scrapers/mlb/mlb_pitcher_scraper.py) |
| `quality_factor()` | same file |
| `sp_factor()` (single-call helper) | same file |
| `blended_sp_factor()` (season + recent) | same file |
| `xwoba_factor()` + `blend_with_xwoba()` | same file |
| `fetch_factors_for_slate()` (orchestration) | same file |

The `fetch_factors_for_slate()` orchestrator accepts an optional `splits_loader` parameter; when supplied, it pulls prior-season xwOBA per pitcher and applies the stage-3 blend. Without it, stage-2 is the final value.

## What this factor *doesn't* model

- **Pitcher arsenal / pitch-mix** — not yet harvested. Sandbox-pending feature.
- **Catcher framing** — Statcast publishes per-catcher framing runs but we don't ingest. Backlog.
- **Times-through-the-order penalty** — implicit in the per-game FIP, not modeled separately.
- **Umpire** — strike-zone effects on K rate aren't yet in the SP factor. Top backlog item.
- **Park effects on HR rate** — applied at the run-projection layer, not here.

## BRAND_GUIDE link

Serves the *Process > Picks* core value: every game has a documented SP factor that's auditable to a specific formula and inputs, regardless of whether the resulting pick clears the gate.
