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


SEASON_WEIGHT = 0.45
RECENT_WEIGHT = 0.30
OPPONENT_WEIGHT = 0.25
RECENT_WINDOW = 10

LEAGUE_AVG_RUNS_PER_TEAM = 4.5
LEAGUE_AVG_F1_RUNS_PER_TEAM = 0.55
LEAGUE_AVG_F5_RUNS_PER_TEAM = 2.4
LEAGUE_F1_SCORE_RATE = 0.27

WIN_PROB_SLOPE = 0.45


def _logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


class ProjectionModel:
    """Aggregates per-team stats and projects matchup outcomes."""

    def __init__(self, games: list[dict]):
        self.games = sorted(games, key=lambda g: g.get("date", ""))
        self.team_games: dict[str, list[dict]] = defaultdict(list)
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

    def _aggregate(self, rows: list[dict]) -> dict:
        """Compute per-game averages over a list of team-view rows."""
        n = len(rows)
        if n == 0:
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
            "rs_pg": sum(r["rs"] for r in rows) / n,
            "ra_pg": sum(r["ra"] for r in rows) / n,
            "f1_rs_pg": sum(r["f1_rs"] for r in rows) / n,
            "f1_ra_pg": sum(r["f1_ra"] for r in rows) / n,
            "f5_rs_pg": sum(r["f5_rs"] for r in rows) / n,
            "f5_ra_pg": sum(r["f5_ra"] for r in rows) / n,
            "f1_score_rate": sum(1 for r in rows if r["scored_in_f1"]) / n,
            "f1_allow_rate": sum(1 for r in rows if r["allowed_in_f1"]) / n,
            "win_pct": sum(1 for r in rows if r["won"]) / n,
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

    def project_matchup(self, away: str, home: str) -> dict:
        """Project all six bet metrics for a single matchup."""
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
        home_win_prob = _logistic(WIN_PROB_SLOPE * margin)
        away_win_prob = 1.0 - home_win_prob

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
            "f5_away_proj": round(away_f5, 2),
            "f5_home_proj": round(home_f5, 2),
            "f5_total_proj": round(away_f5 + home_f5, 2),
            "f5_pick": (
                home if home_f5 > away_f5
                else away if away_f5 > home_f5
                else "PUSH"
            ),
            "f1_away_proj": round(away_f1, 2),
            "f1_home_proj": round(home_f1, 2),
            "f1_total_proj": round(away_f1 + home_f1, 2),
            "nrfi_prob": round(nrfi_prob, 3),
            "yrfi_prob": round(1 - nrfi_prob, 3),
            "nrfi_pick": "NRFI" if nrfi_prob >= 0.5 else "YRFI",
            "away_total_proj": round(away_runs, 2),
            "home_total_proj": round(home_runs, 2),
            "model_meta": {
                "season_weight": SEASON_WEIGHT,
                "recent_weight": RECENT_WEIGHT,
                "opponent_weight": OPPONENT_WEIGHT,
                "recent_window": RECENT_WINDOW,
                "away_games_used": a["season"]["n"],
                "home_games_used": h["season"]["n"],
            },
        }

    def project_slate(self, slate: list[dict]) -> list[dict]:
        """Project every matchup in today's slate.

        slate items must have at least: away_team, home_team, game_pk, game_time
        """
        out = []
        for g in slate:
            proj = self.project_matchup(g["away_team"], g["home_team"])
            proj["date"] = g.get("date")
            proj["game_pk"] = g.get("game_pk")
            proj["game_time"] = g.get("game_time")
            out.append(proj)
        return out
