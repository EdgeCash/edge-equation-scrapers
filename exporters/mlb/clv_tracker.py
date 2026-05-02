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
from datetime import datetime
from pathlib import Path
from typing import Optional

PICKS_LOG_NAME = "picks_log.json"


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

    # ---------------- summary -------------------------------------------

    def summary(self) -> dict:
        data = self.load()
        picks = data["picks"]
        with_close = [p for p in picks if p.get("clv_pct") is not None]

        overall = self._clv_stats(with_close)
        by_type: dict[str, dict] = defaultdict(list)
        for p in with_close:
            by_type[p["bet_type"]].append(p)

        return {
            "picks_total": len(picks),
            "picks_with_close": len(with_close),
            "overall": overall,
            "by_bet_type": {
                bt: self._clv_stats(rows) for bt, rows in by_type.items()
            },
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
