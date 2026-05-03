"""
MLB Player Props Backtest Engine — EXPERIMENTAL.
================================================
Walks the historical games + boxscores in `data/backfill/mlb/` to
grade what our prop projections WOULD have produced. Strict no-
look-ahead: for game G on date D, we project using each player's
running stats accumulated from D-prior games only.

Output: per-prop-type and per-season Brier, hit rate, simulated ROI
at flat -110, and the cold-start games skipped. Sandboxed to
`data/experimental/props_backtests/`.

This is the analysis layer that turns the boxscore tarballs from the
backfill workflow into model evidence. If a prop type's Brier is
clearly under 0.25 across multiple seasons, that's the first signal
it might eventually deserve to clear the BRAND_GUIDE gate.

Per-season memory cost: ~190 MB (boxscores fully extracted into a
dict before iteration). Per-season time: ~2-5 minutes on a typical
machine — most of it is JSON parsing.
"""

from __future__ import annotations

import json
import statistics
import tarfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from models.mlb.player_props import (
    pitcher_strikeouts,
    batter_hits,
    batter_total_bases,
    avg_ip_per_start,
    expected_abs_for_lineup_slot,
    PITCHER_K_LINES,
    BATTER_HITS_LINES,
    BATTER_TB_LINES,
    LEAGUE_K_PER_9,
    LEAGUE_BAA,
)

FLAT_DECIMAL_ODDS = 1.909  # -110


def _settle_units(won: bool, odds: float = FLAT_DECIMAL_ODDS) -> float:
    return round(odds - 1, 4) if won else -1.0


class PropsBacktestEngine:
    """Multi-season prop backtest. Streams boxscores from each season's
    `boxscores.tar.gz`, walks games chronologically, projects pre-game
    props using running per-player stats, grades against actuals."""

    def __init__(self, backfill_dir: Path | str):
        self.backfill_dir = Path(backfill_dir)

    # ---------------- public ---------------------------------------------

    def run(self, seasons: list[int]) -> dict:
        """Run the backtest across the listed seasons. Returns a dict
        with overall and per-prop-type summaries plus per-season detail."""
        per_prop: dict[str, list[dict]] = defaultdict(list)
        per_season: dict[int, dict] = {}
        total_games = 0
        total_skipped = 0

        for season in sorted(seasons):
            season_dir = self.backfill_dir / str(season)
            games_path = season_dir / "games.json"
            tarball_path = season_dir / "boxscores.tar.gz"

            if not games_path.exists():
                print(f"  [{season}] no games.json; skipping season")
                continue
            if not tarball_path.exists():
                print(f"  [{season}] no boxscores.tar.gz; skipping season")
                continue

            print(f"  [{season}] loading boxscores...", flush=True)
            boxes_by_pk = self._load_season_boxscores(tarball_path)

            print(f"  [{season}] {len(boxes_by_pk):,} boxscores loaded; walking games...", flush=True)
            games = json.loads(games_path.read_text())
            games.sort(key=lambda g: g.get("date", ""))

            # Per-season running stats. Reset each season — old players
            # turn over, rosters change, etc. Keeps the Brier estimate
            # sharper for what the model can actually use at inference.
            pitcher_running: dict[int, dict] = {}
            batter_running: dict[int, dict] = {}
            team_k_running: dict[str, dict] = defaultdict(
                lambda: {"k": 0, "pa": 0}
            )

            season_per_prop: dict[str, list[dict]] = defaultdict(list)
            season_games = 0
            season_skipped = 0

            for game in games:
                pk = game.get("game_pk")
                box = boxes_by_pk.get(pk)
                if box is None:
                    season_skipped += 1
                    continue

                # Project pre-game props for both starting pitchers + all
                # batters in the boxscore lineup. Running stats reflect
                # PRIOR games only — current game stats haven't been
                # folded in yet.
                pre_game = self._project_pre_game(
                    box, pitcher_running, batter_running, team_k_running,
                )

                # Grade each projection against the actual stat line.
                graded = self._grade(pre_game, box)
                for entry in graded:
                    per_prop[entry["prop_type"]].append(entry)
                    season_per_prop[entry["prop_type"]].append(entry)

                # Now fold this game's stats into the running aggregates
                # so the next game in chronological order sees them.
                self._update_running(
                    box, pitcher_running, batter_running, team_k_running,
                )

                season_games += 1

            total_games += season_games
            total_skipped += season_skipped
            per_season[season] = {
                "n_games": season_games,
                "n_skipped": season_skipped,
                "summary": self._summarize_per_prop(season_per_prop),
            }
            print(
                f"  [{season}] graded {season_games:,} games "
                f"({season_skipped} skipped); "
                f"{sum(len(v) for v in season_per_prop.values()):,} prop bets"
            )

        return {
            "as_of": datetime.utcnow().isoformat() + "Z",
            "seasons": sorted(seasons),
            "total_games_graded": total_games,
            "total_games_skipped": total_skipped,
            "overall": self._summarize_per_prop(per_prop),
            "per_season": per_season,
        }

    # ---------------- streaming load -------------------------------------

    @staticmethod
    def _load_season_boxscores(tarball_path: Path) -> dict[int, dict]:
        """Extract every boxscore JSON from a season's tarball into a
        dict keyed by game_pk. ~190 MB resident per season — fine."""
        out: dict[int, dict] = {}
        with tarfile.open(tarball_path, "r:gz") as tar:
            for member in tar:
                if not member.isfile() or not member.name.endswith(".json"):
                    continue
                base = Path(member.name).stem
                try:
                    pk = int(base)
                except ValueError:
                    continue
                f = tar.extractfile(member)
                if f is None:
                    continue
                try:
                    out[pk] = json.loads(f.read())
                except json.JSONDecodeError:
                    continue
        return out

    # ---------------- projection (pre-game) ------------------------------

    def _project_pre_game(
        self,
        box: dict,
        pitcher_running: dict[int, dict],
        batter_running: dict[int, dict],
        team_k_running: dict[str, dict],
    ) -> list[dict]:
        """Build pre-game prop projections from running stats only."""
        out: list[dict] = []
        teams = box.get("teams") or {}

        away_team = ((teams.get("away") or {}).get("team") or {}).get("abbreviation")
        home_team = ((teams.get("home") or {}).get("team") or {}).get("abbreviation")

        for side_label, side, opp_label, opp_side in (
            ("away", teams.get("away") or {}, "home", teams.get("home") or {}),
            ("home", teams.get("home") or {}, "away", teams.get("away") or {}),
        ):
            team_code = (
                away_team if side_label == "away" else home_team
            )
            opp_code = (
                home_team if side_label == "away" else away_team
            )

            # ----- starting pitcher -----
            sp_id = self._starting_pitcher_id(side)
            if sp_id is not None:
                sp_running = pitcher_running.get(sp_id) or {}
                opp_team = team_k_running.get(opp_code) or {"k": 0, "pa": 0}
                if opp_team["pa"] >= 50:
                    opp_k_per_9 = (opp_team["k"] / opp_team["pa"]) * 38 / 9
                else:
                    opp_k_per_9 = LEAGUE_K_PER_9
                expected_ip = avg_ip_per_start(
                    sp_running.get("ip"), sp_running.get("starts"),
                )
                proj = pitcher_strikeouts(
                    season_ks=sp_running.get("ks"),
                    season_ip=sp_running.get("ip"),
                    opp_team_k_per_9=opp_k_per_9,
                    expected_ip_today=expected_ip,
                )
                for line in PITCHER_K_LINES:
                    out.append({
                        "prop_type": f"pitcher_ks_o{line}".replace(".", "_"),
                        "side": side_label,
                        "player_id": sp_id,
                        "line": line,
                        "model_prob": proj[f"over_{line}".replace(".", "_")],
                        "team": team_code,
                        "opp_team": opp_code,
                    })

            # ----- batting order -----
            opp_baa = self._opp_pitcher_baa(opp_side, pitcher_running)
            for slot, batter_id in self._iter_batters(side):
                br = batter_running.get(batter_id) or {}
                avg = (br.get("hits") / br["ab"]) if br.get("ab", 0) else None
                slg = (br.get("tb") / br["ab"]) if br.get("ab", 0) else None
                expected_abs = expected_abs_for_lineup_slot(slot)

                hits_proj = batter_hits(
                    season_avg=avg,
                    season_ab=br.get("ab"),
                    expected_abs=expected_abs,
                    opp_pitcher_baa=opp_baa,
                )
                for line in BATTER_HITS_LINES:
                    out.append({
                        "prop_type": f"batter_hits_o{line}".replace(".", "_"),
                        "side": side_label,
                        "player_id": batter_id,
                        "line": line,
                        "model_prob": hits_proj[f"over_{line}".replace(".", "_")],
                        "team": team_code,
                        "opp_team": opp_code,
                    })

                tb_proj = batter_total_bases(
                    season_slg=slg,
                    season_ab=br.get("ab"),
                    expected_abs=expected_abs,
                    opp_pitcher_baa=opp_baa,
                )
                for line in BATTER_TB_LINES:
                    out.append({
                        "prop_type": f"batter_tb_o{line}".replace(".", "_"),
                        "side": side_label,
                        "player_id": batter_id,
                        "line": line,
                        "model_prob": tb_proj[f"over_{line}".replace(".", "_")],
                        "team": team_code,
                        "opp_team": opp_code,
                    })
        return out

    # ---------------- grading -----------------------------------------

    @staticmethod
    def _grade(projections: list[dict], box: dict) -> list[dict]:
        """Compare each projection to the actual stat line from the
        boxscore. Returns a list of records with prop_type, line,
        model_prob, actual, won, units."""
        teams = box.get("teams") or {}
        out: list[dict] = []

        for proj in projections:
            side = proj["side"]
            pid = proj["player_id"]
            line = proj["line"]
            prop = proj["prop_type"]
            team_box = teams.get(side) or {}
            player = (team_box.get("players") or {}).get(f"ID{pid}") or {}
            stats = player.get("stats") or {}

            if prop.startswith("pitcher_ks_"):
                actual = (stats.get("pitching") or {}).get("strikeOuts")
            elif prop.startswith("batter_hits_"):
                actual = (stats.get("batting") or {}).get("hits")
            elif prop.startswith("batter_tb_"):
                actual = (stats.get("batting") or {}).get("totalBases")
            else:
                continue

            if actual is None:
                continue
            try:
                actual = int(actual)
            except (TypeError, ValueError):
                continue

            # Half-point lines; no push possible. OVER wins when actual > line.
            won = actual > line
            out.append({
                "prop_type": prop,
                "line": line,
                "model_prob": proj["model_prob"],
                "actual": actual,
                "won": won,
                "units": _settle_units(won),
                "team": proj["team"],
                "opp_team": proj["opp_team"],
            })
        return out

    # ---------------- running stats updates ------------------------------

    @staticmethod
    def _update_running(
        box: dict,
        pitcher_running: dict[int, dict],
        batter_running: dict[int, dict],
        team_k_running: dict[str, dict],
    ) -> None:
        """Fold this game's stats into per-player running totals."""
        teams = box.get("teams") or {}
        for side_label in ("away", "home"):
            side = teams.get(side_label) or {}
            team_code = ((side.get("team") or {}).get("abbreviation"))
            players = side.get("players") or {}

            sp_id = PropsBacktestEngine._starting_pitcher_id(side)

            for key, p in players.items():
                pid_raw = (p.get("person") or {}).get("id")
                if pid_raw is None:
                    continue
                pid = int(pid_raw)
                stats = p.get("stats") or {}
                pitch = stats.get("pitching") or {}
                bat = stats.get("batting") or {}

                # Pitching contribution
                ip_str = pitch.get("inningsPitched")
                if ip_str:
                    ip_val = PropsBacktestEngine._ip_to_float(ip_str)
                    if ip_val > 0:
                        pr = pitcher_running.setdefault(pid, {
                            "ks": 0, "ip": 0.0, "starts": 0,
                            "hr": 0, "bb": 0, "hbp": 0,
                        })
                        pr["ks"] += int(pitch.get("strikeOuts") or 0)
                        pr["ip"] += ip_val
                        pr["bb"] += int(pitch.get("baseOnBalls") or 0)
                        pr["hbp"] += int(pitch.get("hitByPitch") or 0)
                        pr["hr"] += int(pitch.get("homeRuns") or 0)
                        if pid == sp_id:
                            pr["starts"] += 1

                # Batting contribution
                ab = bat.get("atBats")
                if ab is not None:
                    try:
                        ab_int = int(ab)
                    except (TypeError, ValueError):
                        ab_int = 0
                    if ab_int > 0:
                        br = batter_running.setdefault(pid, {
                            "ab": 0, "hits": 0, "tb": 0, "ks": 0,
                        })
                        br["ab"] += ab_int
                        br["hits"] += int(bat.get("hits") or 0)
                        br["tb"] += int(bat.get("totalBases") or 0)
                        br["ks"] += int(bat.get("strikeOuts") or 0)

                        # Team-level K aggregation for the offensive K rate
                        if team_code:
                            t = team_k_running[team_code]
                            t["k"] += int(bat.get("strikeOuts") or 0)
                            t["pa"] += int(bat.get("plateAppearances") or 0)

    # ---------------- helpers ----------------------------------------

    @staticmethod
    def _starting_pitcher_id(team_box: dict) -> int | None:
        """First entry of the pitchers array is the starter (per MLB
        boxscore convention)."""
        pitchers = team_box.get("pitchers") or []
        if pitchers:
            try:
                return int(pitchers[0])
            except (TypeError, ValueError):
                return None
        return None

    @staticmethod
    def _iter_batters(team_box: dict):
        """Yield (lineup_slot, player_id) for the starting batting order
        only — skip pinch hitters / pinch runners that don't have a
        starting slot."""
        seen: set[int] = set()
        # Prefer `battingOrder` array if present (some endpoints), else
        # fall back to `batters` (the more standard field).
        order = team_box.get("battingOrder") or team_box.get("batters") or []
        slot = 0
        for pid_raw in order:
            try:
                pid = int(pid_raw)
            except (TypeError, ValueError):
                continue
            if pid in seen:
                continue
            seen.add(pid)
            slot += 1
            if slot > 9:
                break
            yield slot, pid

    @staticmethod
    def _opp_pitcher_baa(
        opp_team_box: dict,
        pitcher_running: dict[int, dict],
    ) -> float | None:
        sp_id = PropsBacktestEngine._starting_pitcher_id(opp_team_box)
        if sp_id is None:
            return None
        pr = pitcher_running.get(sp_id)
        # We don't track BAA in running pitcher stats above; approximate
        # via batters' season AVG against this pitcher's team. For MVP
        # we return None and let the projection fall back to LEAGUE_BAA.
        return None

    @staticmethod
    def _ip_to_float(ip) -> float:
        """MLB IP format: '6.1' = 6 1/3 IP, '6.2' = 6 2/3 IP."""
        if ip is None:
            return 0.0
        try:
            s = str(ip)
            whole, _, frac = s.partition(".")
            thirds = {"": 0, "0": 0, "1": 1 / 3, "2": 2 / 3}.get(frac, 0)
            return float(whole) + thirds
        except (TypeError, ValueError):
            return 0.0

    # ---------------- summarization ----------------------------------

    @staticmethod
    def _summarize_per_prop(per_prop: dict[str, list[dict]]) -> dict:
        rows = []
        all_records = []
        for prop_type, records in sorted(per_prop.items()):
            n = len(records)
            wins = sum(1 for r in records if r["won"])
            losses = n - wins
            units = round(sum(r["units"] for r in records), 2)
            scored = [(r["model_prob"], 1 if r["won"] else 0) for r in records]
            brier = (
                round(
                    sum((p - y) ** 2 for p, y in scored) / n, 4,
                ) if n else None
            )
            rows.append({
                "prop_type": prop_type,
                "n": n,
                "wins": wins,
                "losses": losses,
                "hit_rate": round(wins / n * 100, 1) if n else 0.0,
                "units_pl": units,
                "roi_pct": round(units / n * 100, 2) if n else 0.0,
                "brier": brier,
            })
            all_records.extend(records)

        n_all = len(all_records)
        wins_all = sum(1 for r in all_records if r["won"])
        units_all = round(sum(r["units"] for r in all_records), 2)
        scored_all = [(r["model_prob"], 1 if r["won"] else 0) for r in all_records]
        brier_all = (
            round(sum((p - y) ** 2 for p, y in scored_all) / n_all, 4)
            if n_all else None
        )
        return {
            "by_prop_type": rows,
            "overall": {
                "n": n_all,
                "wins": wins_all,
                "losses": n_all - wins_all,
                "hit_rate": round(wins_all / n_all * 100, 1) if n_all else 0.0,
                "units_pl": units_all,
                "roi_pct": round(units_all / n_all * 100, 2) if n_all else 0.0,
                "brier": brier_all,
            },
        }
