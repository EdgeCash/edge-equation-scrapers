"""
Projection model for MLB game-level bets.
=========================================
Builds per-team aggregates from a season-to-date backfill of completed
games and produces matchup projections for the six game-results bet
types: Moneyline, Run Line, Totals, First 5, First Inning, Team Totals.

Methodology: weighted blend of (season pace, last-10 form, opponent pace).
    proj_team_runs = w_season * team_season_RS_pg
                   + w_recent * team_recent_RS_pg
                   + w_opp    * opponent_RA_pg

Win probability is derived from projected margin via a logistic curve
calibrated to MLB's typical run-differential -> win-rate relationship
(roughly 0.10 per run of margin in expectation).
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime

from exporters.mlb.park_factors import park_factor


SEASON_WEIGHT = 0.45
RECENT_WEIGHT = 0.30
OPPONENT_WEIGHT = 0.25
RECENT_WINDOW = 10

LEAGUE_AVG_RUNS_PER_TEAM = 4.5
LEAGUE_AVG_F1_RUNS_PER_TEAM = 0.55
LEAGUE_AVG_F5_RUNS_PER_TEAM = 2.4
LEAGUE_F1_SCORE_RATE = 0.27

# Bayesian shrinkage: pseudo-count of league-average "ghost games" added
# to every team's running totals. Larger k = more pull toward league mean,
# better for early-season noise; smaller k = more responsive to real form.
SHRINKAGE_K = 15

# Phase 2: exponential decay on the SEASON aggregate so recent games
# count more than ones from a month ago. 14-day half-life means a game
# 14 days ago contributes half as much as a game today; a game 28 days
# ago, a quarter as much. The hard "last 10 games" recent component
# stays alongside this for very-fresh-form sensitivity.
DEFAULT_DECAY_HALF_LIFE_DAYS = 14.0

WIN_PROB_SLOPE = 0.45

# Standard deviations for deriving probabilities from point projections.
# Calibrated to typical MLB game-to-game variance. These are the DEFAULT
# values; ProjectionModel(calibration={...}) overrides them with values
# computed from actual backtest residuals.
TOTAL_SD = 3.0          # full-game total runs
TEAM_TOTAL_SD = 2.2     # one team's runs
MARGIN_SD = 3.5         # full-game run margin
F5_TOTAL_SD = 2.2       # first-5-innings total
F5_MARGIN_SD = 2.2      # first-5-innings margin


def _logistic(x: float) -> float:
    # clip to avoid overflow on huge projected margins
    x = max(-30.0, min(30.0, x))
    return 1.0 / (1.0 + math.exp(-x))


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via erf — no scipy dependency."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def prob_over(line: float, mean: float, sd: float) -> float:
    """P(X > line) for X ~ Normal(mean, sd^2). Kept for legacy callers
    (margin distributions, etc.). Game/team totals should prefer the
    Poisson form below since runs are non-negative integer counts.
    """
    if sd <= 0:
        return 1.0 if mean > line else 0.0
    return 1.0 - _norm_cdf((line - mean) / sd)


# ---------- Poisson helpers (count-distribution math) -------------------
#
# Runs in a baseball game are integer counts and right-skewed; modeling
# them as Poisson is sharper than normal-CDF, especially in the tails
# (very low or very high totals) where the normal approximation is worst.
# Sum of independent Poissons is Poisson, so for a game total we can use
# λ_total = λ_away + λ_home and stay closed-form.

def poisson_pmf(k: int, lam: float) -> float:
    """P(X = k) for X ~ Poisson(λ). Stable via log-gamma."""
    if k < 0 or lam <= 0:
        return 0.0
    return math.exp(-lam + k * math.log(lam) - math.lgamma(k + 1))


def poisson_cdf(k: int, lam: float) -> float:
    """P(X <= k) for X ~ Poisson(λ). Direct PMF summation."""
    if k < 0:
        return 0.0
    if lam <= 0:
        return 1.0
    total = 0.0
    for i in range(k + 1):
        total += poisson_pmf(i, lam)
    return min(1.0, total)


def prob_over_under_poisson(line: float, lam: float) -> tuple[float, float, float]:
    """Returns (P(over), P(under), P(push)) for a Poisson-distributed
    integer total at the given betting line.

    Half-point lines (e.g. 8.5) have P(push)=0. Whole-number lines
    (e.g. 9.0) put the PMF at the line into push.
    """
    if lam <= 0:
        return (0.0, 1.0, 0.0)
    threshold = math.floor(line)
    p_le_threshold = poisson_cdf(threshold, lam)
    p_over = 1.0 - p_le_threshold
    if abs(line - round(line)) < 1e-9:  # whole-number line
        p_push = poisson_pmf(int(line), lam)
        p_under = p_le_threshold - p_push
    else:
        p_push = 0.0
        p_under = p_le_threshold
    return (p_over, p_under, p_push)


def prob_margin_atleast_poisson(threshold: int, lam_a: float, lam_b: float) -> float:
    """P(X - Y >= threshold) where X ~ Poisson(λ_a), Y ~ Poisson(λ_b).

    X - Y follows a Skellam distribution. We compute the tail via direct
    summation over Y rather than relying on Bessel functions:

        P(X - Y >= t) = sum_{y >= 0} P(Y=y) * P(X >= y+t)

    Truncated at y = mean(λ_b)+8σ for numerical efficiency; tail mass
    beyond that is negligible for typical MLB λs (4-7).
    """
    if lam_a <= 0 and lam_b <= 0:
        return 1.0 if threshold <= 0 else 0.0
    y_max = max(20, int(lam_b + 8 * math.sqrt(lam_b)) + 5)
    total = 0.0
    for y in range(y_max + 1):
        p_y = poisson_pmf(y, lam_b)
        if p_y < 1e-12:
            continue
        x_min = y + threshold
        if x_min <= 0:
            p_x = 1.0
        else:
            p_x = 1.0 - poisson_cdf(x_min - 1, lam_a)
        total += p_y * p_x
    return min(1.0, max(0.0, total))


# ---------- Negative Binomial helpers (over-dispersed counts) ------------
#
# Real MLB run totals are over-dispersed: empirical variance > mean.
# Calibrated total_sd from backtest residuals is ~4.6 on a typical mean
# of ~9 runs (variance 21, dispersion ratio 2.36). Poisson assumes
# variance = mean, which makes our probabilities overconfident — Phase 1
# discovered this when 13-20% "edges" appeared on totals (real markets
# don't leave that on the table).
#
# Negative Binomial parameterized by (mean μ, dispersion r):
#     mean      = μ
#     variance  = μ + μ²/r
# Solve for r given mean and target variance:
#     r = μ² / (variance − μ)        when variance > μ
# As r → ∞, NegBin collapses to Poisson.

def negbin_pmf(k: int, mu: float, r: float) -> float:
    """P(X = k) for NegBin parameterized by (mean μ, dispersion r)."""
    if k < 0 or mu <= 0 or r <= 0:
        return 0.0
    log_pmf = (
        math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1)
        + r * math.log(r / (r + mu))
        + k * math.log(mu / (r + mu))
    )
    return math.exp(log_pmf)


def negbin_cdf(k: int, mu: float, r: float) -> float:
    """P(X <= k) for NegBin(mean=μ, dispersion=r). Direct PMF summation."""
    if k < 0:
        return 0.0
    if mu <= 0:
        return 1.0
    total = 0.0
    for i in range(k + 1):
        total += negbin_pmf(i, mu, r)
    return min(1.0, total)


def dispersion_from_sd(mu: float, sd: float) -> float | None:
    """Solve for NegBin dispersion r given mean and target SD.

    Returns None when the data is NOT over-dispersed (variance ≤ mean),
    signaling callers to fall back to Poisson.
    """
    if mu <= 0 or sd <= 0:
        return None
    variance = sd * sd
    if variance <= mu:
        return None
    return mu * mu / (variance - mu)


def prob_over_under_negbin(
    line: float, mu: float, r: float,
) -> tuple[float, float, float]:
    """Returns (P(over), P(under), P(push)) for an over-dispersed
    NegBin(μ, r) integer total at the given betting line.
    """
    if mu <= 0 or r is None or r <= 0:
        return (0.0, 1.0, 0.0)
    threshold = math.floor(line)
    p_le_threshold = negbin_cdf(threshold, mu, r)
    p_over = 1.0 - p_le_threshold
    if abs(line - round(line)) < 1e-9:
        p_push = negbin_pmf(int(line), mu, r)
        p_under = p_le_threshold - p_push
    else:
        p_push = 0.0
        p_under = p_le_threshold
    return (p_over, p_under, p_push)


def prob_over_under_smart(
    line: float, mu: float, sd: float | None,
) -> tuple[float, float, float]:
    """Pick NegBin when calibrated SD implies over-dispersion; otherwise
    Poisson. Caller passes the calibrated empirical SD; we derive
    dispersion per-projection so r tracks the actual mean.
    """
    if sd is None or sd <= 0:
        return prob_over_under_poisson(line, mu)
    r = dispersion_from_sd(mu, sd)
    if r is None:
        return prob_over_under_poisson(line, mu)
    return prob_over_under_negbin(line, mu, r)


class ProjectionModel:
    """Aggregates per-team stats and projects matchup outcomes.

    Args:
        games: completed-game dicts from MLBGameScraper.
        shrinkage_k: pseudo-count of league-average "ghost games" mixed
            into each team's totals (Bayesian shrinkage to mean).
        calibration: optional dict overriding hardcoded SDs and the ML
            logistic slope with values fitted from backtest residuals.
        apply_park_factors: when True, multiplies projected runs by the
            home venue's park factor.
    """

    def __init__(
        self,
        games: list[dict],
        shrinkage_k: int = SHRINKAGE_K,
        calibration: dict | None = None,
        apply_park_factors: bool = True,
        decay_half_life_days: float = DEFAULT_DECAY_HALF_LIFE_DAYS,
    ):
        self.games = sorted(games, key=lambda g: g.get("date", ""))
        self.team_games: dict[str, list[dict]] = defaultdict(list)
        self.shrinkage_k = shrinkage_k
        self.apply_park_factors = apply_park_factors
        self.decay_half_life_days = decay_half_life_days

        # Reference date for decay weighting. The latest game in the
        # dataset is "today" from the model's perspective — for the live
        # daily build that's yesterday's game; for backtest iteration N
        # it's game N-1. Both correctly avoid look-ahead.
        self._reference_date = self._latest_game_date()

        cal = calibration or {}
        self.total_sd = cal.get("total_sd", TOTAL_SD)
        self.team_total_sd = cal.get("team_total_sd", TEAM_TOTAL_SD)
        self.margin_sd = cal.get("margin_sd", MARGIN_SD)
        self.f5_total_sd = cal.get("f5_total_sd", F5_TOTAL_SD)
        self.f5_margin_sd = cal.get("f5_margin_sd", F5_MARGIN_SD)
        self.win_prob_slope = cal.get("win_prob_slope", WIN_PROB_SLOPE)
        self.calibration = cal

        self._build()

    def _latest_game_date(self) -> datetime | None:
        if not self.games:
            return None
        for g in reversed(self.games):
            d = g.get("date")
            if not d:
                continue
            try:
                return datetime.strptime(d, "%Y-%m-%d")
            except (TypeError, ValueError):
                continue
        return None

    def _decay_weights(self, rows: list[dict]) -> list[float]:
        """Per-row exponential decay weights, anchored at the model's
        reference date. Weight at days_ago=0 is 1.0, at half_life it's 0.5.
        Returns a list of 1.0s when decay is disabled (half_life <= 0).
        """
        if self.decay_half_life_days <= 0 or self._reference_date is None:
            return [1.0] * len(rows)
        weights: list[float] = []
        hl = self.decay_half_life_days
        for r in rows:
            d = r.get("date")
            if not d:
                weights.append(1.0)
                continue
            try:
                game_date = datetime.strptime(d, "%Y-%m-%d")
            except (TypeError, ValueError):
                weights.append(1.0)
                continue
            days_ago = max(0, (self._reference_date - game_date).days)
            weights.append(0.5 ** (days_ago / hl))
        return weights

    def _build(self) -> None:
        """Index every completed game from each team's perspective."""
        for g in self.games:
            away, home = g["away_team"], g["home_team"]
            self.team_games[away].append(self._team_view(g, side="away"))
            self.team_games[home].append(self._team_view(g, side="home"))

    @staticmethod
    def _team_view(game: dict, side: str) -> dict:
        """Per-team view of a game so we can compute RS / RA / F1 / F5 rolls."""
        opp_side = "home" if side == "away" else "away"
        rs = game[f"{side}_score"]
        ra = game[f"{opp_side}_score"]
        f1_rs = game[f"f1_{side}"]
        f1_ra = game[f"f1_{opp_side}"]
        f5_rs = game[f"f5_{side}"]
        f5_ra = game[f"f5_{opp_side}"]
        return {
            "date": game["date"],
            "team": game[f"{side}_team"],
            "opponent": game[f"{opp_side}_team"],
            "side": side,
            "rs": rs,
            "ra": ra,
            "f1_rs": f1_rs,
            "f1_ra": f1_ra,
            "f5_rs": f5_rs,
            "f5_ra": f5_ra,
            "scored_in_f1": f1_rs > 0,
            "allowed_in_f1": f1_ra > 0,
            "won": rs > ra,
        }

    def _aggregate(
        self,
        rows: list[dict],
        shrunk: bool = True,
        weights: list[float] | None = None,
    ) -> dict:
        """Per-game averages with optional Bayesian shrinkage to league mean
        and optional per-row weights (for exponential decay).

        Without weights: (sum + k * league_avg) / (n + k) — original behavior.
        With weights: (Σ w_i * x_i + k * league_avg) / (Σ w_i + k).

        Effective sample size is the sum of weights, so very-old games
        contribute almost nothing toward both numerator and denominator —
        the shrinkage prior automatically dominates when recent samples
        are thin.
        """
        n_raw = len(rows)
        if weights is None:
            weights = [1.0] * n_raw
        elif len(weights) != n_raw:
            raise ValueError("weights length must match rows length")

        n_eff = sum(weights)
        k = self.shrinkage_k if shrunk else 0
        denom = n_eff + k

        if denom == 0:
            return {
                "n": 0,
                "n_eff": 0.0,
                "rs_pg": LEAGUE_AVG_RUNS_PER_TEAM,
                "ra_pg": LEAGUE_AVG_RUNS_PER_TEAM,
                "f1_rs_pg": LEAGUE_AVG_F1_RUNS_PER_TEAM,
                "f1_ra_pg": LEAGUE_AVG_F1_RUNS_PER_TEAM,
                "f5_rs_pg": LEAGUE_AVG_F5_RUNS_PER_TEAM,
                "f5_ra_pg": LEAGUE_AVG_F5_RUNS_PER_TEAM,
                "f1_score_rate": LEAGUE_F1_SCORE_RATE,
                "f1_allow_rate": LEAGUE_F1_SCORE_RATE,
                "win_pct": 0.5,
            }

        def w_sum_field(field: str) -> float:
            return sum(w * r[field] for w, r in zip(weights, rows))

        def w_sum_pred(pred) -> float:
            return sum(w for w, r in zip(weights, rows) if pred(r))

        return {
            "n": n_raw,
            "n_eff": round(n_eff, 2),
            "rs_pg":
                (w_sum_field("rs") + k * LEAGUE_AVG_RUNS_PER_TEAM) / denom,
            "ra_pg":
                (w_sum_field("ra") + k * LEAGUE_AVG_RUNS_PER_TEAM) / denom,
            "f1_rs_pg":
                (w_sum_field("f1_rs") + k * LEAGUE_AVG_F1_RUNS_PER_TEAM) / denom,
            "f1_ra_pg":
                (w_sum_field("f1_ra") + k * LEAGUE_AVG_F1_RUNS_PER_TEAM) / denom,
            "f5_rs_pg":
                (w_sum_field("f5_rs") + k * LEAGUE_AVG_F5_RUNS_PER_TEAM) / denom,
            "f5_ra_pg":
                (w_sum_field("f5_ra") + k * LEAGUE_AVG_F5_RUNS_PER_TEAM) / denom,
            "f1_score_rate":
                (w_sum_pred(lambda r: r["scored_in_f1"]) + k * LEAGUE_F1_SCORE_RATE) / denom,
            "f1_allow_rate":
                (w_sum_pred(lambda r: r["allowed_in_f1"]) + k * LEAGUE_F1_SCORE_RATE) / denom,
            "win_pct":
                (w_sum_pred(lambda r: r["won"]) + k * 0.5) / denom,
        }

    def team_summary(self, team: str) -> dict:
        """Season (decay-weighted) + last-N (unweighted) aggregates.

        The "season" component now applies exponential decay so a team
        that was hot a month ago doesn't drag a current cold streak.
        The "recent" component stays as a hard last-N window for
        very-fresh-form sensitivity that even decay can't capture
        (e.g., a roster overhaul a week ago).
        """
        rows = self.team_games.get(team, [])
        season_weights = self._decay_weights(rows)
        season = self._aggregate(rows, weights=season_weights)
        recent = self._aggregate(rows[-RECENT_WINDOW:])
        return {"team": team, "season": season, "recent": recent}

    @staticmethod
    def _blend(season: float, recent: float, opp: float) -> float:
        return (
            SEASON_WEIGHT * season
            + RECENT_WEIGHT * recent
            + OPPONENT_WEIGHT * opp
        )

    def project_matchup(
        self,
        away: str,
        home: str,
        away_sp: dict | None = None,
        home_sp: dict | None = None,
        away_bp: dict | None = None,
        home_bp: dict | None = None,
        weather: dict | None = None,
        away_lineup: dict | None = None,
        home_lineup: dict | None = None,
    ) -> dict:
        """Project all six bet metrics for a single matchup.

        away_sp / home_sp / away_bp / home_bp are optional dicts:
            {"name": str, "era": float, "factor": float, ...}

        Pitching influence on the OPPOSING team's runs:
          - Full-game runs blend 5/9 SP factor + 4/9 bullpen factor
            (matches typical SP-vs-RP innings split).
          - F5 runs blend 90% SP / 10% bullpen — SP usually carries the
            whole window.

        When a factor isn't supplied (no probable SP, missing bullpen
        stats) it falls back to 1.0 and the corresponding share has no
        adjustment effect.
        """
        a = self.team_summary(away)
        h = self.team_summary(home)

        away_runs = self._blend(
            a["season"]["rs_pg"], a["recent"]["rs_pg"], h["season"]["ra_pg"]
        )
        home_runs = self._blend(
            h["season"]["rs_pg"], h["recent"]["rs_pg"], a["season"]["ra_pg"]
        )

        away_f5 = self._blend(
            a["season"]["f5_rs_pg"], a["recent"]["f5_rs_pg"], h["season"]["f5_ra_pg"]
        )
        home_f5 = self._blend(
            h["season"]["f5_rs_pg"], h["recent"]["f5_rs_pg"], a["season"]["f5_ra_pg"]
        )

        away_sp_factor = (away_sp or {}).get("factor", 1.0)
        home_sp_factor = (home_sp or {}).get("factor", 1.0)
        away_bp_factor = (away_bp or {}).get("factor", 1.0)
        home_bp_factor = (home_bp or {}).get("factor", 1.0)

        SP_SHARE = 5.0 / 9.0
        BP_SHARE = 4.0 / 9.0
        F5_SP_SHARE = 0.90
        F5_BP_SHARE = 0.10

        # OPP pitching staff suppresses each team's offense.
        away_runs *= SP_SHARE * home_sp_factor + BP_SHARE * home_bp_factor
        home_runs *= SP_SHARE * away_sp_factor + BP_SHARE * away_bp_factor
        away_f5 *= F5_SP_SHARE * home_sp_factor + F5_BP_SHARE * home_bp_factor
        home_f5 *= F5_SP_SHARE * away_sp_factor + F5_BP_SHARE * away_bp_factor

        # Park factor — both teams' offensive output is scaled equally
        # by the home venue's run environment.
        pf = park_factor(home) if self.apply_park_factors else 1.0
        away_runs *= pf
        home_runs *= pf
        away_f5 *= pf
        home_f5 *= pf

        # Weather — temperature scales total run environment. Domes and
        # missing data both produce a neutral 1.0. Applied to F5 too at
        # half magnitude (less of the game is played, smaller swing).
        wf = (weather or {}).get("factor", 1.0)
        wf_f5 = 1.0 + (wf - 1.0) * 0.5
        away_runs *= wf
        home_runs *= wf
        away_f5 *= wf_f5
        home_f5 *= wf_f5

        # Lineup — missing star bats reduce the team's offensive output.
        # Factor of 1.0 when lineup isn't posted yet (no penalty for
        # missing data). Applied to both full game and F5 since the
        # scratched bat misses the entire game.
        a_lineup_factor = (away_lineup or {}).get("factor", 1.0)
        h_lineup_factor = (home_lineup or {}).get("factor", 1.0)
        away_runs *= a_lineup_factor
        home_runs *= h_lineup_factor
        away_f5 *= a_lineup_factor
        home_f5 *= h_lineup_factor

        away_f1 = self._blend(
            a["season"]["f1_rs_pg"], a["recent"]["f1_rs_pg"], h["season"]["f1_ra_pg"]
        )
        home_f1 = self._blend(
            h["season"]["f1_rs_pg"], h["recent"]["f1_rs_pg"], a["season"]["f1_ra_pg"]
        )

        away_f1_score_p = self._blend(
            a["season"]["f1_score_rate"],
            a["recent"]["f1_score_rate"],
            h["season"]["f1_allow_rate"],
        )
        home_f1_score_p = self._blend(
            h["season"]["f1_score_rate"],
            h["recent"]["f1_score_rate"],
            a["season"]["f1_allow_rate"],
        )
        away_f1_score_p = max(0.0, min(1.0, away_f1_score_p))
        home_f1_score_p = max(0.0, min(1.0, home_f1_score_p))
        nrfi_prob = (1 - away_f1_score_p) * (1 - home_f1_score_p)

        margin = home_runs - away_runs
        home_win_prob = _logistic(self.win_prob_slope * margin)
        away_win_prob = 1.0 - home_win_prob

        # Run-line: bet the projected UNDERDOG at +1.5 rather than the
        # projected favorite at -1.5. Backtest evidence: when picking the
        # favorite to cover -1.5 the model hit 36% (huge -ROI). The model
        # IS sharp on which team is the favorite — it's just that
        # favorites historically cover -1.5 only ~40% of the time. Taking
        # the contrary side at +1.5 inverts that math.
        #
        # P(underdog +1.5 covers) = P(fav_margin <= 1) = 1 - P(fav_margin >= 2)
        # No push possible since 1.5 isn't an integer margin.
        if margin >= 0:
            fav_cover_prob = prob_over(1.5, margin, self.margin_sd)
            rl_fav_team = home
            rl_underdog_team = away
        else:
            fav_cover_prob = prob_over(1.5, -margin, self.margin_sd)
            rl_fav_team = away
            rl_underdog_team = home
        rl_cover_prob = 1.0 - fav_cover_prob

        f5_margin = home_f5 - away_f5
        if f5_margin > 0:
            f5_win_prob = 1 - _norm_cdf(-f5_margin / self.f5_margin_sd)
        elif f5_margin < 0:
            f5_win_prob = 1 - _norm_cdf(f5_margin / self.f5_margin_sd)
        else:
            f5_win_prob = 0.5

        return {
            "away_team": away,
            "home_team": home,
            "away_runs_proj": round(away_runs, 2),
            "home_runs_proj": round(home_runs, 2),
            "total_proj": round(away_runs + home_runs, 2),
            "margin_proj": round(margin, 2),
            "ml_pick": home if home_win_prob >= 0.5 else away,
            "home_win_prob": round(home_win_prob, 3),
            "away_win_prob": round(away_win_prob, 3),
            "rl_fav": rl_fav_team,
            "rl_pick": rl_underdog_team,           # the side we ACTUALLY bet
            "rl_pick_point": 1.5,                  # +1.5 underdog spread
            "rl_margin_proj": round(abs(margin), 2),
            "rl_fav_covers_1_5": abs(margin) >= 1.5,
            "rl_fav_cover_prob": round(fav_cover_prob, 3),
            "rl_cover_prob": round(rl_cover_prob, 3),  # P(rl_pick covers +1.5)
            "f5_away_proj": round(away_f5, 2),
            "f5_home_proj": round(home_f5, 2),
            "f5_total_proj": round(away_f5 + home_f5, 2),
            "f5_pick": (
                home if home_f5 > away_f5
                else away if away_f5 > home_f5
                else "PUSH"
            ),
            "f5_win_prob": round(f5_win_prob, 3),
            "f1_away_proj": round(away_f1, 2),
            "f1_home_proj": round(home_f1, 2),
            "f1_total_proj": round(away_f1 + home_f1, 2),
            "nrfi_prob": round(nrfi_prob, 3),
            "yrfi_prob": round(1 - nrfi_prob, 3),
            "nrfi_pick": "NRFI" if nrfi_prob >= 0.5 else "YRFI",
            "away_total_proj": round(away_runs, 2),
            "home_total_proj": round(home_runs, 2),
            "away_sp": away_sp,
            "home_sp": home_sp,
            "away_bp": away_bp,
            "home_bp": home_bp,
            "weather": weather,
            "away_lineup": away_lineup,
            "home_lineup": home_lineup,
            "model_meta": {
                "season_weight": SEASON_WEIGHT,
                "recent_weight": RECENT_WEIGHT,
                "opponent_weight": OPPONENT_WEIGHT,
                "recent_window": RECENT_WINDOW,
                "shrinkage_k": self.shrinkage_k,
                "park_factor": pf,
                "weather_factor": wf,
                "away_sp_factor": away_sp_factor,
                "home_sp_factor": home_sp_factor,
                "away_bp_factor": away_bp_factor,
                "home_bp_factor": home_bp_factor,
                "away_lineup_factor": a_lineup_factor,
                "home_lineup_factor": h_lineup_factor,
                "total_sd": self.total_sd,
                "margin_sd": self.margin_sd,
                "win_prob_slope": self.win_prob_slope,
                "calibrated": bool(self.calibration),
                "away_games_used": a["season"]["n"],
                "home_games_used": h["season"]["n"],
            },
        }

    def project_slate(self, slate: list[dict]) -> list[dict]:
        """Project every matchup in today's slate.

        slate items must have at least: away_team, home_team, game_pk,
        game_time. They MAY also carry away_sp / home_sp dicts (from
        MLBPitcherScraper); when present, those flow into the projection
        as starting-pitcher adjustments.
        """
        out = []
        for g in slate:
            proj = self.project_matchup(
                g["away_team"], g["home_team"],
                away_sp=g.get("away_sp"),
                home_sp=g.get("home_sp"),
                away_bp=g.get("away_bp"),
                home_bp=g.get("home_bp"),
                weather=g.get("weather"),
                away_lineup=g.get("away_lineup"),
                home_lineup=g.get("home_lineup"),
            )
            proj["date"] = g.get("date")
            proj["game_pk"] = g.get("game_pk")
            proj["game_time"] = g.get("game_time")
            out.append(proj)
        return out
