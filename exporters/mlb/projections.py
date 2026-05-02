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
    """P(X > line) for X ~ Normal(mean, sd^2)."""
    if sd <= 0:
        return 1.0 if mean > line else 0.0
    return 1.0 - _norm_cdf((line - mean) / sd)


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
    ):
        self.games = sorted(games, key=lambda g: g.get("date", ""))
        self.team_games: dict[str, list[dict]] = defaultdict(list)
        self.shrinkage_k = shrinkage_k
        self.apply_park_factors = apply_park_factors

        cal = calibration or {}
        self.total_sd = cal.get("total_sd", TOTAL_SD)
        self.team_total_sd = cal.get("team_total_sd", TEAM_TOTAL_SD)
        self.margin_sd = cal.get("margin_sd", MARGIN_SD)
        self.f5_total_sd = cal.get("f5_total_sd", F5_TOTAL_SD)
        self.f5_margin_sd = cal.get("f5_margin_sd", F5_MARGIN_SD)
        self.win_prob_slope = cal.get("win_prob_slope", WIN_PROB_SLOPE)
        self.calibration = cal

        self._build()

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

    def _aggregate(self, rows: list[dict], shrunk: bool = True) -> dict:
        """Per-game averages with optional Bayesian shrinkage to league mean.

        Shrunk estimate: (sum + k * league_avg) / (n + k)
        With k=15 and a team that's played 30 games at 5.5 RPG, the shrunk
        rate is (165 + 15*4.5) / 45 = 5.17 — pulled meaningfully toward the
        league average until the sample is large enough to dominate.
        """
        n = len(rows)
        k = self.shrinkage_k if shrunk else 0
        denom = n + k

        if denom == 0:
            return {
                "n": 0,
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

        return {
            "n": n,
            "rs_pg":
                (sum(r["rs"] for r in rows) + k * LEAGUE_AVG_RUNS_PER_TEAM) / denom,
            "ra_pg":
                (sum(r["ra"] for r in rows) + k * LEAGUE_AVG_RUNS_PER_TEAM) / denom,
            "f1_rs_pg":
                (sum(r["f1_rs"] for r in rows) + k * LEAGUE_AVG_F1_RUNS_PER_TEAM) / denom,
            "f1_ra_pg":
                (sum(r["f1_ra"] for r in rows) + k * LEAGUE_AVG_F1_RUNS_PER_TEAM) / denom,
            "f5_rs_pg":
                (sum(r["f5_rs"] for r in rows) + k * LEAGUE_AVG_F5_RUNS_PER_TEAM) / denom,
            "f5_ra_pg":
                (sum(r["f5_ra"] for r in rows) + k * LEAGUE_AVG_F5_RUNS_PER_TEAM) / denom,
            "f1_score_rate":
                (sum(1 for r in rows if r["scored_in_f1"]) + k * LEAGUE_F1_SCORE_RATE) / denom,
            "f1_allow_rate":
                (sum(1 for r in rows if r["allowed_in_f1"]) + k * LEAGUE_F1_SCORE_RATE) / denom,
            "win_pct":
                (sum(1 for r in rows if r["won"]) + k * 0.5) / denom,
        }

    def team_summary(self, team: str) -> dict:
        """Season + last-N aggregates for a team."""
        rows = self.team_games.get(team, [])
        season = self._aggregate(rows)
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
    ) -> dict:
        """Project all six bet metrics for a single matchup.

        away_sp / home_sp are optional dicts from MLBPitcherScraper:
            {"name": str, "era": float, "ip": float, "factor": float, ...}
        When provided, the OPPOSING team's offense is scaled by that
        pitcher's quality factor (so home_sp suppresses away_runs and
        vice versa). F5 projections get a slightly stronger SP weight
        since the SP is usually the only pitcher of record through 5.
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

        # Starting-pitcher adjustment. Full-game blend is 70/30
        # (SP / bullpen baseline); F5 leans 90/10 since the SP usually
        # carries those innings.
        away_sp_factor = (away_sp or {}).get("factor", 1.0)
        home_sp_factor = (home_sp or {}).get("factor", 1.0)
        away_runs *= 0.70 * home_sp_factor + 0.30
        home_runs *= 0.70 * away_sp_factor + 0.30
        away_f5 *= 0.90 * home_sp_factor + 0.10
        home_f5 *= 0.90 * away_sp_factor + 0.10

        # Park factor — both teams' offensive output is scaled equally
        # by the home venue's run environment.
        pf = park_factor(home) if self.apply_park_factors else 1.0
        away_runs *= pf
        home_runs *= pf
        away_f5 *= pf
        home_f5 *= pf

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

        # Run-line: probability the projected favorite covers -1.5
        f5_margin = home_f5 - away_f5
        if margin >= 0:
            rl_cover_prob = prob_over(1.5, margin, self.margin_sd)
        else:
            rl_cover_prob = prob_over(1.5, -margin, self.margin_sd)

        # First 5: win probability for the projected F5 favorite
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
            "rl_fav": home if margin >= 0 else away,
            "rl_margin_proj": round(abs(margin), 2),
            "rl_fav_covers_1_5": abs(margin) >= 1.5,
            "rl_cover_prob": round(rl_cover_prob, 3),
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
            "model_meta": {
                "season_weight": SEASON_WEIGHT,
                "recent_weight": RECENT_WEIGHT,
                "opponent_weight": OPPONENT_WEIGHT,
                "recent_window": RECENT_WINDOW,
                "shrinkage_k": self.shrinkage_k,
                "park_factor": pf,
                "away_sp_factor": away_sp_factor,
                "home_sp_factor": home_sp_factor,
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
            )
            proj["date"] = g.get("date")
            proj["game_pk"] = g.get("game_pk")
            proj["game_time"] = g.get("game_time")
            out.append(proj)
        return out
