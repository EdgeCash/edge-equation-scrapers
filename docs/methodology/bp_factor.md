# Bullpen (BP) factor

## What it is

A multiplicative adjustment applied to the OPPOSING team's projected runs based on the relief corps' season quality, modulated by recent workload. A rested elite pen scales opp-runs *down*; an exhausted bad pen scales them *up*.

## Why it matters

The starting pitcher pitches ~5-6 innings; the bullpen covers the remaining 3-4. Late-inning runs disproportionately decide outcomes (because the trailing team is throwing meaningless mop-up arms while the leading team is closing with leverage). Modeling the bullpen with the same care as the SP catches the half of the game the SP factor misses.

## The formula (in production)

Two stages: a season-quality factor (Bayesian-shrunk like the SP), then a workload-fatigue multiplier from last-3-day usage.

### Stage 1 — season-quality factor

```
weighted_ERA = (relief_ERA × relief_IP + LEAGUE_ERA × IP_PRIOR_BULLPEN) / (relief_IP + IP_PRIOR_BULLPEN)
season_factor = clamp(weighted_ERA / LEAGUE_ERA, FACTOR_MIN, FACTOR_MAX)
```

Same shape as the SP-factor stage-1, but the IP prior is much larger (`IP_PRIOR_BULLPEN = 150.0` vs `IP_PRIOR = 50.0` for SPs). Bullpens accumulate IP faster across many arms, so the prior should pull harder before season-aggregate stabilizes.

### Stage 2 — workload-fatigue multiplier

```
extra_IP = max(0, bp_ip_recent - 3.0 × n_games_recent)
fatigue_factor = min(1.15, 1.0 + extra_IP × 0.015)
combined = clamp(season_factor × fatigue_factor, FACTOR_MIN, FACTOR_MAX)
```

The "normal" load is roughly 3 IP per game (starter goes 6, bullpen covers the rest of a 9-inning game). Anything above that across the prior 3 days adds 1.5% to the multiplier per excess IP, capped at 1.15× (a 15% ceiling on fatigue effect).

The clamp is applied to the *combined* factor — a tired-but-elite pen (e.g. season factor 0.85 × fatigue 1.15 = 0.978) ends up near neutral, never above the FACTOR_MAX cap.

### When workload data isn't available

If `target_date` isn't supplied to `fetch_bullpen_factors()`, only stage 1 runs; `fatigue_factor = 1.0`. The daily build always passes the date, so production uses the combined factor.

## Constants in production

| Constant | Value | Why this number |
|---|---|---|
| `LEAGUE_ERA` | `4.20` | Same as `LEAGUE_FIP` since both are calibrated to the same scale. |
| `IP_PRIOR_BULLPEN` | `150.0` | Larger than SP prior because bullpen samples accumulate faster. |
| `MIN_IP_FOR_SIGNAL` | `5.0` | Below this many relief IP, season_factor = 1.0. |
| `FACTOR_MIN` / `FACTOR_MAX` | `0.70` / `1.30` | Same band as SP factor. |
| Normal BP IP per game | `3.0` | Starter ≈ 6 IP, BP covers ~3 IP in a typical 9-inning game. |
| Fatigue rate per excess IP | `0.015` (1.5%) | Empirical estimate; 15% ceiling means a maximally tired pen gives up ~15% more runs. |
| Fatigue cap | `1.15` | Hard upper bound — even a maximally tired pen can't more than 15%-multiply expected runs in our model. |
| Lookback window | `3 days` | Captures back-to-back-to-back workload patterns; longer windows dilute the signal. |

## Implementation

| Component | Location |
|---|---|
| `bullpen_factor()` (single-call season helper) | [`scrapers/mlb/mlb_pitcher_scraper.py`](../../scrapers/mlb/mlb_pitcher_scraper.py) |
| `fetch_team_bullpen_stats()` | same file |
| `fetch_recent_bullpen_workload()` (last-3-days IP) | same file |
| `_team_bullpen_ip_in_box()` (per-game extraction) | same file |
| `fetch_bullpen_factors()` (orchestration with `target_date`) | same file |

API cost added by workload tracking: ~46 ESPN/Stats API calls per daily build (1 schedule + ~45 boxscores). ~5-8 seconds of harvest at typical request speed.

## What this factor *doesn't* model

- **Closer / setup-man availability flags** — IP-based fatigue is a proxy. The cleaner signal is "Closer X is unavailable due to back-to-back outings" but that requires beat-reporter Twitter (a scraper we don't have). On the candidate list as a manual-data-collection feature.
- **Specific arm fatigue** — IP doesn't differentiate between an 8-pitch save and a 30-pitch escape. Pitch-count tracking is on the deeper backlog.
- **Long-relief depth** — full bullpen quality is treated as one factor; the actual likely-to-pitch arms could be modeled separately.

## BRAND_GUIDE link

Serves the *Process > Picks* core value and supports the **Totals** and late-inning **ML** markets specifically (where the bullpen has the largest leverage). Direct contributor to the markets currently passing the gate.
