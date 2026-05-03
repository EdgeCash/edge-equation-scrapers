"""
MLB Platoon Splits Scraper. EXPERIMENTAL.
=========================================
Per-player vs-LHP / vs-RHP season splits. Tier-1 feature ingestion
for the props projector — most prop lines move 5–15% based on the
opposing pitcher's handedness, but our current model uses a single
season-aggregate rate. This scraper closes that gap.

Data source: MLB Stats API (statsapi.mlb.com), unmetered, no auth.
Endpoint: /people/{playerId}/stats?stats=statSplits&group=...&sitCodes=vl,vr

Strategy:
  1. Discover every player who appeared in a season by walking the
     boxscore tarball already harvested by MLBBackfillScraper. No API
     calls needed for player discovery.
  2. For each hitter, pull vL/vR hitting splits.
  3. For each pitcher, pull vL/vR pitching splits.
  4. Persist both per season as a single JSON file.

Output (per season):
    data/backfill/mlb/<season>/splits.json
        {
          "meta": {"season": int, "fetched_at": iso, "n_hitters": int,
                   "n_pitchers": int, "errors": int},
          "hitting": {
            "<player_id>": {
              "name": str, "team_id": int|None,
              "vl": {"pa": int, "ab": int, "h": int, "hr": int, ...},
              "vr": {...}
            }, ...
          },
          "pitching": {
            "<player_id>": {
              "name": str, "team_id": int|None,
              "vl": {"bf": int, "ip": float, "k": int, "bb": int, ...},
              "vr": {...}
            }, ...
          }
        }

Idempotent: per-player results are buffered in `splits.partial.json`
during the run so a crashed/interrupted session resumes from the last
saved point. On clean completion the partial file is replaced with
`splits.json`.

Per-season runtime: ~30–60 minutes at default 0.5s interval (~1500
hitters + ~700 pitchers × 0.5s ≈ 18 min, plus retries / network).

Usage (programmatic):
    scraper = MLBSplitsScraper(backfill_root=Path("data/backfill/mlb"))
    scraper.fetch_season(2024)

NOT scheduled. Triggered manually via `.github/workflows/mlb-splits-
backfill.yml`. Output lives in data/backfill/mlb/ alongside games and
boxscores — sandboxed, never under public/.
"""

from __future__ import annotations

import json
import tarfile
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable

import requests

BASE_URL = "https://statsapi.mlb.com/api/v1"
SPLITS_URL = (
    BASE_URL
    + "/people/{player_id}/stats"
      "?stats=statSplits&group={group}&season={season}"
      "&sitCodes=vl,vr&sportId=1"
)

# 0.5s between API calls = polite but not painfully slow.
# 2200 players * 0.5s = ~18 min per season.
DEFAULT_REQUEST_INTERVAL_S = 0.5

# Counting stats we keep per split. Anything else the API returns is
# discarded — we don't want to ship 100 fields per player to git.
HITTING_STAT_FIELDS = (
    "plateAppearances", "atBats", "hits", "doubles", "triples",
    "homeRuns", "rbi", "baseOnBalls", "intentionalWalks", "hitByPitch",
    "strikeOuts", "stolenBases", "totalBases", "sacBunts", "sacFlies",
    "groundIntoDoublePlay", "avg", "obp", "slg", "ops", "babip",
)
PITCHING_STAT_FIELDS = (
    "battersFaced", "inningsPitched", "atBats", "hits", "doubles",
    "triples", "homeRuns", "runs", "earnedRuns", "baseOnBalls",
    "intentionalWalks", "hitByPitch", "strikeOuts", "wildPitches",
    "balks", "era", "whip", "avg", "obp", "slg", "ops", "babip",
)


class MLBSplitsScraper:
    """Per-player vs-LHP / vs-RHP splits harvester for one or more seasons."""

    def __init__(
        self,
        backfill_root: Path,
        request_interval_s: float = DEFAULT_REQUEST_INTERVAL_S,
        max_retries: int = 2,
    ):
        self.backfill_root = Path(backfill_root)
        self.request_interval_s = request_interval_s
        self.max_retries = max_retries
        self._last_request_at = 0.0

    # ---------------- public ---------------------------------------------

    def fetch_seasons(
        self,
        seasons: Iterable[int],
        verbose: bool = True,
    ) -> dict[int, dict]:
        report: dict[int, dict] = {}
        for season in seasons:
            if verbose:
                print(f"\n=== Splits — season {season} ===")
            report[season] = self.fetch_season(season, verbose=verbose)
        return report

    def fetch_season(self, season: int, verbose: bool = True) -> dict:
        season_dir = self.backfill_root / str(season)
        final_path = season_dir / "splits.json"
        partial_path = season_dir / "splits.partial.json"

        if final_path.exists():
            if verbose:
                print(f"  Already complete at {final_path.relative_to(self.backfill_root.parent)}; skipping.")
            return {"skipped": True}

        # Discover the players who actually appeared. Fail loud if the
        # season's boxscore tarball isn't on disk — without it we don't
        # know whose splits to fetch.
        tarball = season_dir / "boxscores.tar.gz"
        if not tarball.exists():
            msg = (
                f"  Season {season}: no boxscores.tar.gz on disk. "
                f"Run MLB Backfill workflow with --with-boxscores first."
            )
            if verbose:
                print(msg)
            return {"error": "missing_boxscores"}

        if verbose:
            print(f"  Discovering players from {tarball.name}...")
        hitters, pitchers, name_team = self._discover_players(tarball)
        if verbose:
            print(f"  Found {len(hitters)} hitters, {len(pitchers)} pitchers.")

        # Resume support.
        result = self._load_partial(partial_path) or {
            "meta": {
                "season": season,
                "fetched_at": None,
                "n_hitters": 0,
                "n_pitchers": 0,
                "errors": 0,
            },
            "hitting": {},
            "pitching": {},
        }

        errors = result["meta"].get("errors", 0)

        # Hitters.
        todo_hit = [pid for pid in sorted(hitters) if str(pid) not in result["hitting"]]
        if verbose:
            print(f"  Hitting splits: {len(todo_hit)} to fetch ({len(result['hitting'])} cached).")
        for i, pid in enumerate(todo_hit, 1):
            entry = self._fetch_player_splits(pid, "hitting", season, HITTING_STAT_FIELDS)
            if entry is None:
                errors += 1
                continue
            name, team_id = name_team.get(pid, (None, None))
            entry["name"] = name
            entry["team_id"] = team_id
            result["hitting"][str(pid)] = entry

            if i % 50 == 0:
                self._save_partial(partial_path, result)
                if verbose:
                    print(f"    [{i}/{len(todo_hit)}] hitters done ({errors} errors)")

        # Pitchers.
        todo_pit = [pid for pid in sorted(pitchers) if str(pid) not in result["pitching"]]
        if verbose:
            print(f"  Pitching splits: {len(todo_pit)} to fetch ({len(result['pitching'])} cached).")
        for i, pid in enumerate(todo_pit, 1):
            entry = self._fetch_player_splits(pid, "pitching", season, PITCHING_STAT_FIELDS)
            if entry is None:
                errors += 1
                continue
            name, team_id = name_team.get(pid, (None, None))
            entry["name"] = name
            entry["team_id"] = team_id
            result["pitching"][str(pid)] = entry

            if i % 50 == 0:
                self._save_partial(partial_path, result)
                if verbose:
                    print(f"    [{i}/{len(todo_pit)}] pitchers done ({errors} errors)")

        result["meta"]["fetched_at"] = datetime.utcnow().isoformat()
        result["meta"]["n_hitters"] = len(result["hitting"])
        result["meta"]["n_pitchers"] = len(result["pitching"])
        result["meta"]["errors"] = errors

        final_path.write_text(json.dumps(result, indent=2, default=str))
        if partial_path.exists():
            partial_path.unlink()

        if verbose:
            size_kb = final_path.stat().st_size / 1024
            print(
                f"  Wrote {final_path.relative_to(self.backfill_root.parent)} "
                f"({size_kb:.0f} KB). hitters={result['meta']['n_hitters']}, "
                f"pitchers={result['meta']['n_pitchers']}, errors={errors}"
            )
        return result["meta"]

    # ---------------- player discovery -----------------------------------

    @staticmethod
    def _discover_players(tarball_path: Path) -> tuple[set[int], set[int], dict[int, tuple[str, int | None]]]:
        """Walk one season's boxscore tarball; return (hitter_ids,
        pitcher_ids, {player_id: (name, team_id)}).

        A player counts as a hitter if they had >= 1 PA across the
        season, as a pitcher if they faced >= 1 batter. Two-way players
        end up in both sets, which is what we want.
        """
        hitters: set[int] = set()
        pitchers: set[int] = set()
        name_team: dict[int, tuple[str, int | None]] = {}

        with tarfile.open(tarball_path, "r:gz") as tar:
            for member in tar:
                if not member.isfile() or not member.name.endswith(".json"):
                    continue
                f = tar.extractfile(member)
                if f is None:
                    continue
                try:
                    box = json.loads(f.read())
                except json.JSONDecodeError:
                    continue
                teams = box.get("teams", {})
                for side in ("home", "away"):
                    team = teams.get(side, {})
                    team_id = team.get("team", {}).get("id")
                    for pid_key, pdata in team.get("players", {}).items():
                        try:
                            pid = int(pid_key.lstrip("ID"))
                        except ValueError:
                            continue
                        person = pdata.get("person", {})
                        name = person.get("fullName") or pdata.get("name")
                        if name and pid not in name_team:
                            name_team[pid] = (name, team_id)
                        stats = pdata.get("stats", {})
                        bat = stats.get("batting", {}) or {}
                        pit = stats.get("pitching", {}) or {}
                        if bat.get("plateAppearances", 0) and bat["plateAppearances"] > 0:
                            hitters.add(pid)
                        if pit.get("battersFaced", 0) and pit["battersFaced"] > 0:
                            pitchers.add(pid)
        return hitters, pitchers, name_team

    # ---------------- API fetch ------------------------------------------

    def _fetch_player_splits(
        self,
        player_id: int,
        group: str,
        season: int,
        keep_fields: tuple[str, ...],
    ) -> dict | None:
        """Hit the splits endpoint for a single player; return
        {"vl": {...}, "vr": {...}} or None on hard failure. Either
        side may be missing (e.g. a hitter with zero PAs vs LHP) — in
        which case we record an empty dict for that side.
        """
        url = SPLITS_URL.format(player_id=player_id, group=group, season=season)
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                resp = requests.get(url, timeout=20)
                if resp.status_code == 404:
                    # Player has no splits at all this season.
                    return {"vl": {}, "vr": {}}
                resp.raise_for_status()
                payload = resp.json()
                break
            except requests.RequestException:
                if attempt >= self.max_retries:
                    return None
                time.sleep(1.0 * (2 ** attempt))

        out = {"vl": {}, "vr": {}}
        for stats_block in payload.get("stats", []):
            for split in stats_block.get("splits", []):
                code = (split.get("split") or {}).get("code")
                if code not in ("vl", "vr"):
                    continue
                stat = split.get("stat", {}) or {}
                trimmed = {k: stat.get(k) for k in keep_fields if k in stat}
                out[code] = trimmed
        return out

    # ---------------- partial-file IO -----------------------------------

    @staticmethod
    def _load_partial(path: Path) -> dict | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _save_partial(path: Path, result: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(result, default=str))
        tmp.replace(path)

    # ---------------- throttle ------------------------------------------

    def _throttle(self) -> None:
        if self.request_interval_s <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        wait = self.request_interval_s - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()
