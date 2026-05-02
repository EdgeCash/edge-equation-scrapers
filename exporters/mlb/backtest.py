"""
Backtest Engine
===============
Walks the season backfill game-by-game, projecting each game using ONLY
data available prior to it, then grading the model's pick against the
actual outcome. Produces hit-rate / ROI / units P&L per bet type plus
a daily cumulative P&L curve and a full bet log.

Uses flat 1-unit bets at -110 (decimal 1.909) across every bet type
since we don't have historical line data for the backfill. ROI is
expressed in units (1 unit risked to win 0.91u at -110).

Bet types tracked:
    moneyline · run_line · totals (8.5/9.0/9.5) · first_5
    first_inning (NRFI/YRFI) · team_totals (3.5/4.5)
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import datetime
from typing import Iterable

from exporters.mlb.projections import ProjectionModel, prob_over, TOTAL_SD, TEAM_TOTAL_SD


FLAT_DECIMAL_ODDS = 1.909  # -110
MIN_BACKFILL_GAMES = 10    # don't bet until model has some signal

TOTAL_LINES = (8.5, 9.0, 9.5)
TEAM_TOTAL_LINES = (3.5, 4.5)


def _fit_logistic_slope(pairs: list[tuple[float, int]], iters: int = 2000) -> float:
    """Maximum-likelihood fit of slope in y = 1/(1+exp(-slope*x)) on (x, y) pairs.

    Pure-stdlib gradient descent; pairs is (margin_proj, won_int_0_or_1).
    Falls back to the default slope if the data is too thin or degenerate.
    """
    if len(pairs) < 30:
        return 0.45
    slope = 0.45
    lr = 0.005
    for _ in range(iters):
        grad = 0.0
        for x, y in pairs:
            xc = max(-30.0, min(30.0, slope * x))
            p = 1.0 / (1.0 + math.exp(-xc))
            grad += (p - y) * x
        grad /= len(pairs)
        slope -= lr * grad
        if abs(grad) < 1e-6:
            break
    return max(0.05, min(2.0, slope))


def _settle(stake: float, decimal_odds: float, won: bool, push: bool = False) -> float:
    """Net unit return for a bet. Flat 1u risked at decimal odds."""
    if push:
        return 0.0
    if won:
        return round(stake * (decimal_odds - 1), 4)
    return -stake


class BacktestEngine:
    """Game-by-game model backtest with no look-ahead."""

    def __init__(
        self,
        games: Iterable[dict],
        min_history: int = MIN_BACKFILL_GAMES,
        decimal_odds: float = FLAT_DECIMAL_ODDS,
    ):
        self.games = sorted(games, key=lambda g: g.get("date", ""))
        self.min_history = min_history
        self.decimal_odds = decimal_odds

    # ---------------- main ------------------------------------------------

    def run(self) -> dict:
        bets: list[dict] = []
        residuals = {
            "total": [],          # (proj_total, actual_total)
            "team_total": [],     # (proj_team_runs, actual_team_runs)
            "margin": [],         # (proj_margin_home_minus_away, actual_margin)
            "f5_total": [],
            "f5_margin": [],
            "ml_pairs": [],       # (proj_margin, won_home_0_or_1)
        }
        for i, game in enumerate(self.games):
            history = self.games[:i]
            if len(history) < self.min_history:
                continue
            model = ProjectionModel(history)
            try:
                proj = model.project_matchup(game["away_team"], game["home_team"])
            except Exception:
                continue
            bets.extend(self._grade_all(proj, game))

            actual_total = game["total"]
            actual_margin = game["home_score"] - game["away_score"]
            proj_margin = proj["home_runs_proj"] - proj["away_runs_proj"]
            residuals["total"].append((proj["total_proj"], actual_total))
            residuals["margin"].append((proj_margin, actual_margin))
            residuals["team_total"].append(
                (proj["away_runs_proj"], game["away_score"])
            )
            residuals["team_total"].append(
                (proj["home_runs_proj"], game["home_score"])
            )
            residuals["f5_total"].append(
                (proj["f5_total_proj"], game["f5_away"] + game["f5_home"])
            )
            residuals["f5_margin"].append(
                (proj["f5_home_proj"] - proj["f5_away_proj"],
                 game["f5_home"] - game["f5_away"])
            )
            residuals["ml_pairs"].append(
                (proj_margin, 1 if actual_margin > 0 else 0)
            )

        return {
            "as_of": datetime.utcnow().isoformat() + "Z",
            "total_games_in_window": len(self.games),
            "first_date": self.games[0]["date"] if self.games else None,
            "last_date": self.games[-1]["date"] if self.games else None,
            "summary_by_bet_type": self._summarize(bets),
            "overall": self._overall(bets),
            "daily_pl": self._daily_pl(bets),
            "calibration": self._calibration(residuals),
            "bets": bets,
        }

    @staticmethod
    def _calibration(residuals: dict) -> dict:
        """Fit SDs from residuals and the ML logistic slope from outcomes."""
        def sd(pairs: list[tuple[float, float]], default: float) -> float:
            if len(pairs) < 30:
                return default
            errs = [a - p for p, a in pairs]
            try:
                value = statistics.pstdev(errs)
            except statistics.StatisticsError:
                return default
            # Guard against pathological values
            return max(0.5, min(default * 2.0, value)) if value > 0 else default

        return {
            "total_sd":      round(sd(residuals["total"], TOTAL_SD), 3),
            "team_total_sd": round(sd(residuals["team_total"], TEAM_TOTAL_SD), 3),
            "margin_sd":     round(sd(residuals["margin"], 3.5), 3),
            "f5_total_sd":   round(sd(residuals["f5_total"], 2.2), 3),
            "f5_margin_sd":  round(sd(residuals["f5_margin"], 2.2), 3),
            "win_prob_slope": round(_fit_logistic_slope(residuals["ml_pairs"]), 4),
            "n_residuals":   len(residuals["total"]),
        }

    # ---------------- per-bet graders ------------------------------------

    def _grade_all(self, proj: dict, game: dict) -> list[dict]:
        return [
            *self._grade_moneyline(proj, game),
            *self._grade_run_line(proj, game),
            *self._grade_totals(proj, game),
            *self._grade_first_5(proj, game),
            *self._grade_first_inning(proj, game),
            *self._grade_team_totals(proj, game),
        ]

    def _grade_moneyline(self, proj: dict, game: dict) -> list[dict]:
        pick = proj["ml_pick"]
        won = (game["ml_winner"] == pick)
        return [self._bet_record(
            game, "moneyline", pick,
            prob=proj["home_win_prob"] if pick == game["home_team"] else proj["away_win_prob"],
            won=won, push=False,
        )]

    def _grade_run_line(self, proj: dict, game: dict) -> list[dict]:
        # Pick: projected favorite at -1.5
        fav = proj["rl_fav"]
        if fav == game["home_team"]:
            margin = game["home_score"] - game["away_score"]
        else:
            margin = game["away_score"] - game["home_score"]
        won = margin >= 2  # covers -1.5
        return [self._bet_record(
            game, "run_line", f"{fav} -1.5",
            prob=proj["rl_cover_prob"], won=won, push=False,
        )]

    def _grade_totals(self, proj: dict, game: dict) -> list[dict]:
        out = []
        actual = game["total"]
        for line in TOTAL_LINES:
            pick_side = "OVER" if proj["total_proj"] > line else "UNDER"
            p_over = prob_over(line, proj["total_proj"], TOTAL_SD)
            prob = p_over if pick_side == "OVER" else 1 - p_over
            push = actual == line
            won = (actual > line) if pick_side == "OVER" else (actual < line)
            out.append(self._bet_record(
                game, "totals", f"{pick_side} {line}",
                prob=prob, won=won, push=push,
            ))
        return out

    def _grade_first_5(self, proj: dict, game: dict) -> list[dict]:
        pick = proj["f5_pick"]
        if pick == "PUSH":
            return []
        winner = game["f5_winner"]
        push = winner == "PUSH"
        won = (winner == pick) if not push else False
        return [self._bet_record(
            game, "first_5", pick,
            prob=proj["f5_win_prob"], won=won, push=push,
        )]

    def _grade_first_inning(self, proj: dict, game: dict) -> list[dict]:
        pick = proj["nrfi_pick"]
        actual_nrfi = game["nrfi"]
        if pick == "NRFI":
            won = actual_nrfi
            prob = proj["nrfi_prob"]
        else:
            won = not actual_nrfi
            prob = proj["yrfi_prob"]
        return [self._bet_record(
            game, "first_inning", pick,
            prob=prob, won=won, push=False,
        )]

    def _grade_team_totals(self, proj: dict, game: dict) -> list[dict]:
        out = []
        for team, runs_proj, runs_actual in (
            (game["away_team"], proj["away_runs_proj"], game["away_score"]),
            (game["home_team"], proj["home_runs_proj"], game["home_score"]),
        ):
            for line in TEAM_TOTAL_LINES:
                pick_side = "OVER" if runs_proj > line else "UNDER"
                p_over = prob_over(line, runs_proj, TEAM_TOTAL_SD)
                prob = p_over if pick_side == "OVER" else 1 - p_over
                push = runs_actual == line
                won = (runs_actual > line) if pick_side == "OVER" else (runs_actual < line)
                out.append(self._bet_record(
                    game, "team_totals", f"{team} {pick_side} {line}",
                    prob=prob, won=won, push=push,
                ))
        return out

    # ---------------- helpers --------------------------------------------

    def _bet_record(
        self,
        game: dict,
        bet_type: str,
        pick: str,
        prob: float,
        won: bool,
        push: bool,
    ) -> dict:
        units = _settle(1.0, self.decimal_odds, won, push)
        return {
            "date": game["date"],
            "matchup": f"{game['away_team']}@{game['home_team']}",
            "bet_type": bet_type,
            "pick": pick,
            "model_prob": round(prob, 3),
            "result": "PUSH" if push else ("WIN" if won else "LOSS"),
            "units": units,
        }

    @staticmethod
    def _summarize(bets: list[dict]) -> list[dict]:
        groups: dict[str, list[dict]] = defaultdict(list)
        for b in bets:
            groups[b["bet_type"]].append(b)

        rows = []
        for bet_type in sorted(groups):
            grp = groups[bet_type]
            wins = sum(1 for b in grp if b["result"] == "WIN")
            losses = sum(1 for b in grp if b["result"] == "LOSS")
            pushes = sum(1 for b in grp if b["result"] == "PUSH")
            graded = wins + losses
            units = round(sum(b["units"] for b in grp), 2)
            rows.append({
                "bet_type": bet_type,
                "bets": len(grp),
                "wins": wins,
                "losses": losses,
                "pushes": pushes,
                "hit_rate": round(wins / graded * 100, 1) if graded else 0.0,
                "units_pl": units,
                "roi_pct": round(units / len(grp) * 100, 2) if grp else 0.0,
            })
        return rows

    @staticmethod
    def _overall(bets: list[dict]) -> dict:
        wins = sum(1 for b in bets if b["result"] == "WIN")
        losses = sum(1 for b in bets if b["result"] == "LOSS")
        pushes = sum(1 for b in bets if b["result"] == "PUSH")
        graded = wins + losses
        units = round(sum(b["units"] for b in bets), 2)
        return {
            "bets": len(bets),
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "hit_rate": round(wins / graded * 100, 1) if graded else 0.0,
            "units_pl": units,
            "roi_pct": round(units / len(bets) * 100, 2) if bets else 0.0,
        }

    @staticmethod
    def _daily_pl(bets: list[dict]) -> list[dict]:
        by_date: dict[str, float] = defaultdict(float)
        for b in bets:
            by_date[b["date"]] += b["units"]

        cumulative = 0.0
        rows = []
        for date in sorted(by_date):
            cumulative += by_date[date]
            rows.append({
                "date": date,
                "daily_units": round(by_date[date], 2),
                "cumulative_units": round(cumulative, 2),
            })
        return rows
