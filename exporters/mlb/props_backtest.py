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

from exporters.mlb.splits_loader import SplitsLoader
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

# At least this many lineup slots must yield a usable splits-based K/PA
# before we trust the splits projection over the running aggregate.
MIN_LINEUP_SLOTS_FOR_SPLITS_K = 5


def _settle_units(won: bool, odds: float = FLAT_DECIMAL_ODDS) -> float:
    return round(odds - 1, 4) if won else -1.0


class PropsBacktestEngine:
    """Multi-season prop backtest. Streams boxscores from each season's
    `boxscores.tar.gz`, walks games chronologically, projects pre-game
    props using running per-player stats, grades against actuals.

    Handedness-aware: if `splits_loader` is provided AND has prior-season
    splits + handedness data on disk, batter and pitcher projections use
    the matchup-specific rate (e.g. Judge vs LHP, Skenes vs LHB) instead
    of the season aggregate. Strict no-look-ahead — only PRIOR-season
    splits are consulted, never current-season.
    """

    def __init__(
        self,
        backfill_dir: Path | str,
        splits_loader: SplitsLoader | None = None,
    ):
        self.backfill_dir = Path(backfill_dir)
        self.splits_loader = splits_loader or SplitsLoader(self.backfill_dir)
        # Track how often we got to use the handedness path so the
        # caller can sanity-check whether splits actually contributed.
        self.splits_usage = {
            "hitter_avg_used": 0,
            "hitter_slg_used": 0,
            "sp_k_via_splits_used": 0,
            "sp_k_fell_back": 0,
        }

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
                # folded in yet. `season` is passed so the splits loader
                # can consult prior-season (no-look-ahead) splits.
                pre_game = self._project_pre_game(
                    box, season, pitcher_running, batter_running, team_k_running,
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
            "splits_usage": dict(self.splits_usage),
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
        season: int,
        pitcher_running: dict[int, dict],
        batter_running: dict[int, dict],
        team_k_running: dict[str, dict],
    ) -> list[dict]:
        """Build pre-game prop projections.

        For each side we build:
          - SP K props, using a splits-blended K/9 if prior-season splits
            cover at least MIN_LINEUP_SLOTS_FOR_SPLITS_K of the opposing
            lineup; otherwise the running-aggregate path.
          - Each starter's hits + total bases, using prior-season vL/vR
            AVG/SLG when the matchup's pitcher handedness is known and
            the player has enough prior-season PAs vs that hand;
            otherwise running-aggregate AVG/SLG.
        """
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
                splits_k_per_9 = self._sp_k_per_9_via_splits(
                    sp_id, season, opp_side,
                )
                if splits_k_per_9 is not None:
                    self.splits_usage["sp_k_via_splits_used"] += 1
                else:
                    self.splits_usage["sp_k_fell_back"] += 1
                proj = pitcher_strikeouts(
                    season_ks=sp_running.get("ks"),
                    season_ip=sp_running.get("ip"),
                    opp_team_k_per_9=opp_k_per_9,
                    expected_ip_today=expected_ip,
                    override_k_per_9=splits_k_per_9,
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
            opp_sp_id = self._starting_pitcher_id(opp_side)
            opp_sp_pitch_hand = (
                self.splits_loader.pitch_hand(opp_sp_id) if opp_sp_id else None
            )
            for slot, batter_id in self._iter_batters(side):
                br = batter_running.get(batter_id) or {}
                running_avg = (br.get("hits") / br["ab"]) if br.get("ab", 0) else None
                running_slg = (br.get("tb") / br["ab"]) if br.get("ab", 0) else None
                running_ab = br.get("ab")
                expected_abs = expected_abs_for_lineup_slot(slot)

                # Prefer prior-season handedness split when available.
                splits_avg = self.splits_loader.hitter_avg_vs(
                    batter_id, season, opp_sp_pitch_hand,
                )
                splits_slg = self.splits_loader.hitter_slg_vs(
                    batter_id, season, opp_sp_pitch_hand,
                )
                splits_pa = self.splits_loader.hitter_pa_vs(
                    batter_id, season, opp_sp_pitch_hand,
                )

                if splits_avg is not None:
                    self.splits_usage["hitter_avg_used"] += 1
                    avg = splits_avg
                    avg_ab = splits_pa
                else:
                    avg = running_avg
                    avg_ab = running_ab

                if splits_slg is not None:
                    self.splits_usage["hitter_slg_used"] += 1
                    slg = splits_slg
                    slg_ab = splits_pa
                else:
                    slg = running_slg
                    slg_ab = running_ab

                hits_proj = batter_hits(
                    season_avg=avg,
                    season_ab=avg_ab,
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
                    season_ab=slg_ab,
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

    # ---------------- splits-aware SP K projection -------------------

    def _sp_k_per_9_via_splits(
        self, sp_id: int, season: int, opp_team_box: dict,
    ) -> float | None:
        """Compute SP's expected K/9 vs the OPPOSING lineup using
        prior-season vL/vR splits. Returns None if we don't have splits
        for the SP, or if fewer than MIN_LINEUP_SLOTS_FOR_SPLITS_K of the
        opposing batters resolve to a usable per-handedness K rate. The
        backtest then falls back to the running-aggregate K/9 path.
        """
        sp_pitch_hand = self.splits_loader.pitch_hand(sp_id)
        if sp_pitch_hand is None:
            return None

        usable_slots = 0
        total_k_per_pa = 0.0
        for _slot, batter_id in self._iter_batters(opp_team_box):
            eff_bat_side = self.splits_loader.effective_bat_side(
                batter_id, sp_pitch_hand,
            )
            if eff_bat_side is None:
                continue
            k_per_pa = self.splits_loader.pitcher_k_per_pa_vs(
                sp_id, season, eff_bat_side,
            )
            if k_per_pa is None:
                continue
            total_k_per_pa += k_per_pa
            usable_slots += 1

        if usable_slots < MIN_LINEUP_SLOTS_FOR_SPLITS_K:
            return None

        avg_k_per_pa = total_k_per_pa / usable_slots
        # ~38 PAs in a 9-IP complete game → K/9 = K/PA × 38.
        return avg_k_per_pa * 38.0

    # ---------------- grading -----------------------------------------

    @staticmethod
    def _grade(projections: list[dict], box: dict) -> list[dict]:
        """Selection-aware grading. For each projection the model picks
        whichever side it favors:
            model_prob_over >= 0.5  →  bet OVER
            model_prob_over <  0.5  →  bet UNDER (with prob = 1 - p_over)

        The Brier-relevant probability is `pick_prob` (the model's
        confidence in the SIDE IT PICKED), not the raw model_prob_over.
        That's what separates "model has skill at picking sides" from
        "base rates favor a direction."

        No edge threshold here — we grade every pick. The runner can
        post-hoc filter by pick_prob to bucket high-confidence picks.
        Lines are .5-only so no push possible.
        """
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

            model_prob_over = proj["model_prob"]
            if model_prob_over >= 0.5:
                pick_side = "OVER"
                pick_prob = model_prob_over
                won = actual > line
            else:
                pick_side = "UNDER"
                pick_prob = 1.0 - model_prob_over
                won = actual < line

            out.append({
                "prop_type": prop,
                "line": line,
                "pick_side": pick_side,
                "pick_prob": round(pick_prob, 4),
                "model_prob_over": round(model_prob_over, 4),
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
        all_records: list[dict] = []
        for prop_type, records in sorted(per_prop.items()):
            rows.append(_stats_row(prop_type, records))
            all_records.extend(records)
        return {
            "by_prop_type": rows,
            "overall": _stats_block(all_records),
            # Confidence-bucket views — "when the model is confident, does
            # it actually win?" Each bucket grades only the picks where
            # the model's chosen-side probability cleared the threshold.
            "by_confidence_bucket": {
                "all_picks": _stats_block(all_records),
                "p>=0.55": _stats_block(
                    [r for r in all_records if r.get("pick_prob", 0) >= 0.55]
                ),
                "p>=0.60": _stats_block(
                    [r for r in all_records if r.get("pick_prob", 0) >= 0.60]
                ),
                "p>=0.65": _stats_block(
                    [r for r in all_records if r.get("pick_prob", 0) >= 0.65]
                ),
            },
        }


def _stats_block(records: list[dict]) -> dict:
    """Aggregate stats over a list of graded records.
    Brier uses pick_prob (model's confidence in the side it picked)."""
    n = len(records)
    if n == 0:
        return {
            "n": 0, "wins": 0, "losses": 0, "hit_rate": 0.0,
            "units_pl": 0.0, "roi_pct": 0.0, "brier": None,
        }
    wins = sum(1 for r in records if r["won"])
    units = round(sum(r["units"] for r in records), 2)
    scored = [
        (r.get("pick_prob", r.get("model_prob_over", 0.5)),
         1 if r["won"] else 0)
        for r in records
    ]
    brier = round(sum((p - y) ** 2 for p, y in scored) / n, 4)
    return {
        "n": n,
        "wins": wins,
        "losses": n - wins,
        "hit_rate": round(wins / n * 100, 1),
        "units_pl": units,
        "roi_pct": round(units / n * 100, 2),
        "brier": brier,
    }


def _stats_row(prop_type: str, records: list[dict]) -> dict:
    """Per-prop-type aggregate stats including OVER vs UNDER breakdown."""
    over = [r for r in records if r.get("pick_side") == "OVER"]
    under = [r for r in records if r.get("pick_side") == "UNDER"]
    base = _stats_block(records)
    return {
        "prop_type": prop_type,
        **base,
        "over_n": len(over),
        "over_hit_rate": _stats_block(over)["hit_rate"],
        "over_units_pl": _stats_block(over)["units_pl"],
        "over_brier": _stats_block(over)["brier"],
        "under_n": len(under),
        "under_hit_rate": _stats_block(under)["hit_rate"],
        "under_units_pl": _stats_block(under)["units_pl"],
        "under_brier": _stats_block(under)["brier"],
    }
