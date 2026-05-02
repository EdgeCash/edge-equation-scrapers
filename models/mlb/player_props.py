"""
MLB Player Props — projection models. EXPERIMENTAL.
====================================================
Pure-math projection helpers for the most common MLB player-prop
markets. Not wired into the live daily card or website. Outputs land
in `data/experimental/mlb-props/` for offline auditing only — per
BRAND_GUIDE Sandbox protocol, no prop ships to the daily card until
we have backtest evidence the gate can be cleared.

Models implemented:
    pitcher_strikeouts(season, opp_team, expected_ip)
        Poisson(λ = (sp_K/9 ⊕ opp_K/9) × expected_ip / 9)
        Returns expected_ks + P(over X.5) for X in {4, 5, 6, 7}.

    batter_hits(season_avg, expected_abs, opp_pitcher_baa)
        Binomial(n=expected_abs, p=avg × pitcher_factor)
        Returns expected_hits + P(over 0.5) + P(over 1.5).

    batter_total_bases(season_slg, expected_abs, opp_pitcher_baa)
        Poisson(λ = SLG × expected_abs × pitcher_factor)
        Returns expected_tb + P(over 1.5/2.5/3.5).

The Poisson approximation for total bases is technically wrong (TB
isn't a count of independent events) but close enough for sandbox
work. A simulation-based version is on the roadmap if backtest
results suggest the approximation is materially miscalibrated.

Imports the existing Poisson helpers from exporters/mlb/projections.py
so we don't duplicate the math. When the migration plan in
models/README.md plays out, those helpers move to
models/distributions.py and this file imports from there.
"""

from __future__ import annotations

from exporters.mlb.projections import poisson_cdf

# League-average baselines for opponent adjustment + thin-sample fallback
LEAGUE_K_PER_9 = 8.6        # MLB-wide modern era
LEAGUE_AVG = 0.245
LEAGUE_BAA = 0.245          # batting avg against (same scale)
LEAGUE_SLG = 0.405

# Default expected IP for a typical SP. Real value comes from
# season_ip / season_starts when available.
DEFAULT_EXPECTED_IP = 5.5
DEFAULT_EXPECTED_ABS = 4.0  # leadoff/middle of order
DEFAULT_BOTTOM_ABS = 3.5    # 8/9 hitters

# Prop lines we care about (matches typical sportsbook offerings)
PITCHER_K_LINES = (4.5, 5.5, 6.5, 7.5)
BATTER_HITS_LINES = (0.5, 1.5)
BATTER_TB_LINES = (1.5, 2.5, 3.5)

MIN_IP_FOR_SIGNAL = 5.0
MIN_AB_FOR_SIGNAL = 30


def pitcher_strikeouts(
    season_ks: int | None,
    season_ip: float | None,
    opp_team_k_per_9: float | None = None,
    expected_ip_today: float = DEFAULT_EXPECTED_IP,
) -> dict:
    """Project a starting pitcher's strikeouts.

    Returns a dict with `expected_ks`, plus `over_X_5` for each line in
    PITCHER_K_LINES. Falls back to league-average K/9 when the season
    sample is too thin to trust.
    """
    if season_ks is None or season_ip is None or season_ip < MIN_IP_FOR_SIGNAL:
        sp_k_per_9 = LEAGUE_K_PER_9
    else:
        sp_k_per_9 = (season_ks / season_ip) * 9.0

    opp = opp_team_k_per_9 if opp_team_k_per_9 is not None else LEAGUE_K_PER_9

    # Equal-weighted blend of pitcher quality + opponent strikeout
    # tendency. Half-point step so the matchup pulls 50%.
    matchup_k_per_9 = (sp_k_per_9 + opp) / 2.0

    expected_ks = matchup_k_per_9 * expected_ip_today / 9.0
    expected_ks = max(0.1, expected_ks)  # avoid Poisson(0) edge case

    out = {
        "expected_ks": round(expected_ks, 2),
        "sp_k_per_9": round(sp_k_per_9, 2),
        "matchup_k_per_9": round(matchup_k_per_9, 2),
        "expected_ip": expected_ip_today,
    }
    for line in PITCHER_K_LINES:
        # P(K count > line) for half-point line = 1 - CDF(floor(line))
        threshold = int(line)
        out[f"over_{line}".replace(".", "_")] = round(
            1.0 - poisson_cdf(threshold, expected_ks), 4,
        )
    return out


def batter_hits(
    season_avg: float | None,
    season_ab: int | None,
    expected_abs: float = DEFAULT_EXPECTED_ABS,
    opp_pitcher_baa: float | None = None,
) -> dict:
    """Project a starting batter's hits.

    Binomial-ish: per-AB hit probability × expected ABs.
    P(over 0.5) = 1 - (1-p)^n
    P(over 1.5) = 1 - (1-p)^n - n × p × (1-p)^(n-1)
    """
    if season_avg is None or season_ab is None or season_ab < MIN_AB_FOR_SIGNAL:
        p = LEAGUE_AVG
    else:
        p = season_avg

    if opp_pitcher_baa is not None and opp_pitcher_baa > 0:
        # Pitcher BAA above league = weak pitcher = batter benefits.
        p *= opp_pitcher_baa / LEAGUE_BAA

    p = max(0.05, min(0.50, p))
    n = expected_abs

    p_zero = (1 - p) ** n
    p_one_or_less = p_zero + n * p * ((1 - p) ** (n - 1))

    return {
        "expected_hits": round(p * n, 3),
        "hit_prob_per_ab": round(p, 3),
        "expected_abs": expected_abs,
        "over_0_5": round(1.0 - p_zero, 4),
        "over_1_5": round(1.0 - min(1.0, p_one_or_less), 4),
    }


def batter_total_bases(
    season_slg: float | None,
    season_ab: int | None,
    expected_abs: float = DEFAULT_EXPECTED_ABS,
    opp_pitcher_baa: float | None = None,
) -> dict:
    """Project a starting batter's total bases.

    Poisson approximation on TB-per-AB rate. SLG is literally TB/AB.
    Approximation: TB are not independent (a HR vs four singles vs a
    triple+single all sum to similar values but with very different
    distributions). Good enough for sandbox eyeballing.
    """
    if season_slg is None or season_ab is None or season_ab < MIN_AB_FOR_SIGNAL:
        rate = LEAGUE_SLG
    else:
        rate = season_slg

    if opp_pitcher_baa is not None and opp_pitcher_baa > 0:
        rate *= opp_pitcher_baa / LEAGUE_BAA

    rate = max(0.05, min(1.50, rate))
    expected_tb = rate * expected_abs
    expected_tb = max(0.1, expected_tb)

    out = {
        "expected_tb": round(expected_tb, 2),
        "tb_per_ab": round(rate, 3),
        "expected_abs": expected_abs,
    }
    for line in BATTER_TB_LINES:
        threshold = int(line)
        out[f"over_{line}".replace(".", "_")] = round(
            1.0 - poisson_cdf(threshold, expected_tb), 4,
        )
    return out


# ---- Helpers ------------------------------------------------------------

def expected_abs_for_lineup_slot(slot: int) -> float:
    """Rough heuristic for ABs per game by lineup position. 1-7 get
    the full slate; 8/9 get fewer."""
    if slot in (8, 9):
        return DEFAULT_BOTTOM_ABS
    return DEFAULT_EXPECTED_ABS


def avg_ip_per_start(season_ip: float | None, season_starts: int | None) -> float:
    """Per-start IP estimate from season totals. Falls back to a typical
    5.5 IP when sample is thin."""
    if season_ip and season_starts and season_starts >= 3:
        return season_ip / season_starts
    return DEFAULT_EXPECTED_IP
