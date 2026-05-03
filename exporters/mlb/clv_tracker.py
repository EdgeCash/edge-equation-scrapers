"""
Closing Line Value (CLV) Tracker
================================
Persists every play that hits Today's Card with the price we took, then
re-snapshots the same line near game-time and records how much the
market moved toward (or away from) our pick.

Why CLV: long-run profitability in sports betting correlates more
strongly with positive CLV than with raw W/L record. A model that
consistently beats the close by even 1-2% is grinding out edge that
will eventually show up as ROI; a model losing to the close is bleeding
EV regardless of short-term wins.

CLV in implied-probability terms:
    pick_implied    = 1 / pick_decimal_odds
    closing_implied = 1 / closing_decimal_odds
    clv_pct = (closing_implied - pick_implied) * 100

Positive CLV = the market moved toward our pick = our price was sharper
than the close.

Storage: a single `picks_log.json` in public/data/mlb/. Each pick is a
dict keyed by a deterministic pick_id (date|matchup|bet_type|pick) so
the morning build is idempotent.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

PICKS_LOG_NAME = "picks_log.json"
CLV_SUMMARY_NAME = "clv_summary.json"


def parse_spec(bet_type: str, pick: str) -> Optional[dict]:
    """Translate (bet_type, pick) into a structured spec the closing
    snapshot can use to look the same bet up in fresh odds data.

    Returns None for bet types we can't currently price (e.g. team_totals
    on the free Odds API tier).
    """
    if not pick:
        return None
    if bet_type == "moneyline":
        return {"type": "moneyline", "team": pick.strip()}
    if bet_type == "run_line":
        # In the current model the run-line pick is always the projected
        # favorite at -1.5; pick string is just the team code.
        return {"type": "run_line", "team": pick.strip(), "point": -1.5}
    if bet_type == "totals":
        # pick like "OVER 9.0" or "UNDER 8.5"
        try:
            side, line = pick.split()
            return {"type": "totals", "side": side.upper(), "line": float(line)}
        except ValueError:
            return None
    if bet_type == "first_5":
        return {"type": "first_5", "team": pick.strip()}
    if bet_type == "first_inning":
        return {"type": "first_inning", "side": pick.strip().upper()}
    return None


def find_closing_price(odds_game: dict, spec: dict) -> Optional[dict]:
    """Look up the price for `spec` in a normalized odds-game dict.

    Returns {"decimal", "american", "book"} or None.
    """
    if not odds_game or not spec:
        return None
    bt = spec.get("type")

    if bt == "moneyline":
        team = spec["team"]
        side = "home" if team == odds_game.get("home_team") else "away"
        return odds_game.get("moneyline", {}).get(side)

    if bt == "run_line":
        team = spec["team"]
        side = "home" if team == odds_game.get("home_team") else "away"
        for o in odds_game.get("run_line", []) or []:
            if o.get("team") == side and abs(o.get("point", 0) - spec["point"]) < 0.01:
                return {
                    "decimal": o["decimal"],
                    "american": o["american"],
                    "book": o["book"],
                }
        return None

    if bt == "totals":
        line = spec["line"]
        side_key = "over" if spec["side"] == "OVER" else "under"
        for offer in odds_game.get("totals", []) or []:
            if abs(offer.get("point", 0) - line) < 0.01:
                return offer.get(side_key)
        return None

    return None


def _settle(pick: dict, won: bool, push: bool) -> dict:
    """Translate (won, push) into a {result, units} dict using the pick's
    actual market price when available; falls back to -110 default."""
    if push:
        return {"result": "PUSH", "units": 0.0}
    price = pick.get("pick_price_dec") or 1.909
    if won:
        return {"result": "WIN", "units": round(price - 1, 4)}
    return {"result": "LOSS", "units": -1.0}


def compute_clv(pick_decimal: float, closing_decimal: float) -> float:
    """CLV in percentage points (positive = our price beat the close)."""
    if pick_decimal is None or closing_decimal is None:
        return 0.0
    if pick_decimal <= 1 or closing_decimal <= 1:
        return 0.0
    pick_implied = 1.0 / pick_decimal
    closing_implied = 1.0 / closing_decimal
    return round((closing_implied - pick_implied) * 100, 3)


class ClvTracker:
    """Reads/writes the persistent pick log and computes CLV summaries."""

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.path = self.output_dir / PICKS_LOG_NAME
        self.summary_path = self.output_dir / CLV_SUMMARY_NAME

    # ---------------- I/O ------------------------------------------------

    def load(self) -> dict:
        if not self.path.exists():
            return {"picks": []}
        try:
            return json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return {"picks": []}

    def save(self, data: dict) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, default=str))
        tmp.replace(self.path)

    def save_summary(self) -> dict:
        """Compute the summary block and persist it as a standalone JSON
        file alongside picks_log.json so the website (and anything else
        that doesn't want to redo the aggregation) can consume it
        directly. Returns the summary dict for in-process callers.
        Includes a `generated_at` timestamp so consumers can check
        freshness."""
        summary = self.summary()
        summary["generated_at"] = datetime.utcnow().isoformat() + "Z"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.summary_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(summary, indent=2, default=str))
        tmp.replace(self.summary_path)
        return summary

    @staticmethod
    def make_pick_id(row: dict) -> str:
        return f"{row['date']}|{row['matchup']}|{row['bet_type']}|{row['pick']}"

    # ---------------- record (morning) ----------------------------------

    def record_picks(
        self,
        card_rows: list[dict],
        odds_source: str,
        slate_meta_by_matchup: Optional[dict[str, dict]] = None,
    ) -> int:
        """Append today's actionable picks to the log. Idempotent on pick_id.

        slate_meta_by_matchup maps "AWAY@HOME" to {"game_pk": int, "game_time": iso}
        so the closing-snapshot job can later gate on first-pitch proximity.
        """
        data = self.load()
        existing_ids = {p["pick_id"] for p in data["picks"]}
        now = datetime.utcnow().isoformat() + "Z"
        meta = slate_meta_by_matchup or {}
        added = 0

        for row in card_rows:
            spec = parse_spec(row.get("bet_type"), row.get("pick"))
            if spec is None:
                continue  # we can't price it later, no point recording
            pid = self.make_pick_id(row)
            if pid in existing_ids:
                continue
            game_meta = meta.get(row.get("matchup")) or {}
            data["picks"].append({
                "pick_id": pid,
                "date": row.get("date"),
                "matchup": row.get("matchup"),
                "game_pk": game_meta.get("game_pk"),
                "game_time": game_meta.get("game_time"),
                "bet_type": row.get("bet_type"),
                "pick": row.get("pick"),
                "spec": spec,
                "model_prob": row.get("model_prob"),
                "edge_pct_at_pick": row.get("edge_pct"),
                "kelly_pct": row.get("kelly_pct"),
                "kelly_advice": row.get("kelly_advice"),
                "pick_price_dec": row.get("market_odds_dec"),
                "pick_price_american": row.get("market_odds_american"),
                "book_at_pick": row.get("book"),
                "pick_taken_at": now,
                "odds_source": odds_source,
                "closing_price_dec": None,
                "closing_price_american": None,
                "closing_book": None,
                "closing_recorded_at": None,
                "clv_pct": None,
                "result": None,
                "units": None,
            })
            added += 1

        if added:
            self.save(data)
        return added

    def pending_today(self, max_minutes_to_first_pitch: int | None = None) -> list[dict]:
        """Return unsettled picks for today, optionally filtered to those
        whose game starts within max_minutes_to_first_pitch minutes from
        now. Used by the closing-snapshot job to decide whether it's
        worth burning an Odds API call.
        """
        data = self.load()
        today = datetime.utcnow().date().isoformat()
        now = datetime.utcnow()

        out = []
        for p in data["picks"]:
            if p.get("closing_price_dec") is not None:
                continue
            if p.get("date") != today:
                continue
            if max_minutes_to_first_pitch is None:
                out.append(p)
                continue

            game_time_str = p.get("game_time")
            if not game_time_str:
                # No game time on file → include (better safe than miss the close).
                out.append(p)
                continue
            try:
                game_dt = datetime.fromisoformat(game_time_str.replace("Z", "+00:00"))
                # Strip timezone for naive comparison (game_dt is UTC-aware,
                # now is naive UTC).
                game_dt_naive = game_dt.replace(tzinfo=None)
            except (TypeError, ValueError):
                out.append(p)
                continue

            minutes_until = (game_dt_naive - now).total_seconds() / 60
            # Include picks where first pitch is within the window (and
            # for ~30 min after, so we still snap if a snapshot fires
            # right at first pitch).
            if -30 <= minutes_until <= max_minutes_to_first_pitch:
                out.append(p)
        return out

    # ---------------- snapshot (closing) --------------------------------

    def record_closing_lines(self, odds: dict) -> dict:
        """Snap closing prices for any unsettled picks whose game is on
        today's slate. Returns a small report dict.
        """
        data = self.load()
        today = datetime.utcnow().date().isoformat()
        odds_by_matchup = {
            f"{g['away_team']}@{g['home_team']}": g
            for g in odds.get("games", [])
        }

        updated = 0
        skipped_no_match = 0
        skipped_already_set = 0
        for pick in data["picks"]:
            if pick.get("closing_price_dec") is not None:
                skipped_already_set += 1
                continue
            if pick.get("date") != today:
                continue  # only snap today's picks; earlier ones missed window

            game = odds_by_matchup.get(pick["matchup"])
            if game is None:
                skipped_no_match += 1
                continue

            price = find_closing_price(game, pick["spec"])
            if not price:
                skipped_no_match += 1
                continue

            pick["closing_price_dec"] = price["decimal"]
            pick["closing_price_american"] = price["american"]
            pick["closing_book"] = price["book"]
            pick["closing_recorded_at"] = datetime.utcnow().isoformat() + "Z"
            pick["clv_pct"] = compute_clv(
                pick.get("pick_price_dec"), price["decimal"]
            )
            updated += 1

        if updated:
            self.save(data)

        return {
            "snapped_today": updated,
            "skipped_no_match": skipped_no_match,
            "skipped_already_set": skipped_already_set,
            "total_picks_in_log": len(data["picks"]),
        }

    # ---------------- grading (post-game) --------------------------------

    def grade_resolved_picks(self, completed_games: list[dict]) -> dict:
        """Grade any logged picks whose game has now completed.

        Idempotent: picks that already have a non-null `result` are
        skipped. Picks for matchups that aren't in the supplied
        completed_games list are left alone (the game probably hasn't
        finished or wasn't surfaced to this scraper run).

        Returns a small report dict with counts.
        """
        data = self.load()

        # Index games by both AWAY@HOME and (away, home) tuple — picks
        # logged from team_totals use "TEAM vs OPP" format which we
        # also need to handle.
        by_matchup: dict[str, dict] = {}
        by_pair: dict[tuple[str, str], dict] = {}
        for g in completed_games:
            away, home = g["away_team"], g["home_team"]
            by_matchup[f"{away}@{home}"] = g
            by_pair[(away, home)] = g
            by_pair[(home, away)] = g

        graded = 0
        not_yet = 0
        for pick in data["picks"]:
            if pick.get("result") is not None:
                continue
            matchup = pick.get("matchup", "")
            game = by_matchup.get(matchup)
            if not game and " vs " in matchup:
                team, opp = matchup.split(" vs ", 1)
                game = by_pair.get((team, opp)) or by_pair.get((opp, team))
            if not game:
                not_yet += 1
                continue
            outcome = self._grade_pick(pick, game)
            if outcome is None:
                continue
            pick["result"] = outcome["result"]
            pick["units"] = outcome["units"]
            pick["graded_at"] = datetime.utcnow().isoformat() + "Z"
            graded += 1

        if graded:
            self.save(data)
        return {
            "graded": graded,
            "still_pending": not_yet,
            "total_picks_in_log": len(data["picks"]),
        }

    @staticmethod
    def _grade_pick(pick: dict, game: dict) -> dict | None:
        """Grade a single pick against a completed game. Returns
        {"result": WIN/LOSS/PUSH, "units": float} or None for bet types
        we can't grade."""
        spec = pick.get("spec") or {}
        bt = spec.get("type")
        away = game["away_team"]
        home = game["home_team"]

        if bt == "moneyline":
            won = (game["ml_winner"] == spec.get("team"))
            return _settle(pick, won, push=False)

        if bt == "run_line":
            # We bet underdog +1.5; we win on a 1-run loss or better.
            team = spec.get("team")
            if team == home:
                margin = game["home_score"] - game["away_score"]
            elif team == away:
                margin = game["away_score"] - game["home_score"]
            else:
                return None
            won = margin >= -1
            return _settle(pick, won, push=False)

        if bt == "totals":
            line = spec.get("line")
            side = spec.get("side")
            actual = game.get("total")
            if line is None or actual is None:
                return None
            if abs(actual - line) < 1e-9:
                return _settle(pick, won=False, push=True)
            if side == "OVER":
                return _settle(pick, won=actual > line, push=False)
            return _settle(pick, won=actual < line, push=False)

        if bt == "first_5":
            team = spec.get("team")
            winner = game.get("f5_winner")
            if winner == "PUSH":
                return _settle(pick, won=False, push=True)
            return _settle(pick, won=(winner == team), push=False)

        if bt == "first_inning":
            side = spec.get("side")
            if side == "NRFI":
                return _settle(pick, won=bool(game.get("nrfi")), push=False)
            return _settle(pick, won=not bool(game.get("nrfi")), push=False)

        return None

    # ---------------- summary -------------------------------------------

    def summary(self) -> dict:
        data = self.load()
        picks = data["picks"]
        with_close = [p for p in picks if p.get("clv_pct") is not None]
        graded = [p for p in picks if p.get("result") in ("WIN", "LOSS", "PUSH")]
        last_30 = self._last_n_days_picks(graded, 30)

        clv_overall = self._clv_stats(with_close)
        record_overall = self._record_stats(graded)
        record_30d = self._record_stats(last_30)

        clv_by_type: dict[str, list] = defaultdict(list)
        for p in with_close:
            clv_by_type[p["bet_type"]].append(p)
        record_by_type: dict[str, list] = defaultdict(list)
        for p in graded:
            record_by_type[p["bet_type"]].append(p)

        return {
            "picks_total": len(picks),
            "picks_with_close": len(with_close),
            "picks_graded": len(graded),
            "overall": clv_overall,           # backwards compat: CLV summary
            "clv_overall": clv_overall,
            "record_overall": record_overall,  # full-history W-L-P + units
            "record_30d": record_30d,          # rolling 30-day window
            "by_bet_type": {
                bt: self._clv_stats(rows) for bt, rows in clv_by_type.items()
            },
            "record_by_bet_type": {
                bt: self._record_stats(rows) for bt, rows in record_by_type.items()
            },
        }

    @staticmethod
    def _last_n_days_picks(picks: list[dict], n: int) -> list[dict]:
        cutoff = datetime.utcnow().date() - timedelta(days=n)
        out = []
        for p in picks:
            try:
                d = datetime.strptime(p["date"], "%Y-%m-%d").date()
            except (KeyError, TypeError, ValueError):
                continue
            if d >= cutoff:
                out.append(p)
        return out

    @staticmethod
    def _record_stats(rows: list[dict]) -> dict:
        wins = sum(1 for r in rows if r.get("result") == "WIN")
        losses = sum(1 for r in rows if r.get("result") == "LOSS")
        pushes = sum(1 for r in rows if r.get("result") == "PUSH")
        graded = wins + losses
        units = round(sum((r.get("units") or 0.0) for r in rows), 2)
        clv_vals = [r["clv_pct"] for r in rows if r.get("clv_pct") is not None]
        return {
            "n": len(rows),
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "hit_rate": round(wins / graded * 100, 1) if graded else 0.0,
            "units_pl": units,
            "roi_pct": round(units / len(rows) * 100, 2) if rows else 0.0,
            "mean_clv_pct": round(sum(clv_vals) / len(clv_vals), 3) if clv_vals else None,
            "n_with_clv": len(clv_vals),
        }

    @staticmethod
    def _clv_stats(rows: list[dict]) -> dict:
        clvs = [r["clv_pct"] for r in rows]
        if not clvs:
            return {
                "n": 0, "mean_clv_pct": None, "median_clv_pct": None,
                "positive": 0, "negative": 0, "neutral": 0,
            }
        return {
            "n": len(clvs),
            "mean_clv_pct": round(sum(clvs) / len(clvs), 3),
            "median_clv_pct": round(statistics.median(clvs), 3),
            "positive": sum(1 for c in clvs if c > 0.01),
            "negative": sum(1 for c in clvs if c < -0.01),
            "neutral":  sum(1 for c in clvs if -0.01 <= c <= 0.01),
        }
