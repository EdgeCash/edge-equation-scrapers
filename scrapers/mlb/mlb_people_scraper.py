"""
MLB Person Handedness Scraper. EXPERIMENTAL.
============================================
One-shot bulk harvester for `pitchHand.code` and `batSide.code` per
player. Required for handedness-aware prop projections — boxscores
expose only `person.id` / `fullName`, not handedness, so we need a
separate lookup table to know which split (vL vs vR) to apply when
projecting a given matchup.

Data source: MLB Stats API /api/v1/people?personIds=1,2,3 (bulk).
Up to ~100 IDs per call; 4,647 unique IDs across our 4-season splits
files = ~50 calls = under 1 minute of wall-clock at the polite 0.5s
default interval.

Strategy:
  1. Walk every season's splits.json on disk; collect the union of
     player IDs (hitters + pitchers).
  2. Skip any IDs already present in the on-disk people.json (idempotent
     resumption — re-running is cheap).
  3. Bulk-fetch the rest via /people?personIds=...
  4. Persist a single combined people.json keyed by player_id.

Output:
    data/backfill/mlb/people.json
        {
          "meta": {"fetched_at": iso, "n_players": int},
          "players": {
            "<player_id>": {
              "name": str,
              "bat_side": "L" | "R" | "S" | null,   # S = switch hitter
              "pitch_hand": "L" | "R" | null
            }, ...
          }
        }

Usage (programmatic):
    scraper = MLBPersonScraper(backfill_root=Path("data/backfill/mlb"))
    scraper.run()

NOT scheduled. Manual trigger via the matching workflow. Output is
sandboxed under data/backfill/, never under public/.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable

import requests

PEOPLE_URL = "https://statsapi.mlb.com/api/v1/people?personIds={ids}"

# 100 IDs per request: comfortably within the URL length limit and
# the API's documented batch cap. Bigger batches risk silent truncation.
DEFAULT_BATCH_SIZE = 100
DEFAULT_REQUEST_INTERVAL_S = 0.5


class MLBPersonScraper:
    """Bulk handedness harvester for every player in the splits files."""

    def __init__(
        self,
        backfill_root: Path,
        batch_size: int = DEFAULT_BATCH_SIZE,
        request_interval_s: float = DEFAULT_REQUEST_INTERVAL_S,
        max_retries: int = 2,
    ):
        self.backfill_root = Path(backfill_root)
        self.batch_size = batch_size
        self.request_interval_s = request_interval_s
        self.max_retries = max_retries
        self._last_request_at = 0.0

    # ---------------- public ---------------------------------------------

    def run(self, verbose: bool = True) -> dict:
        """Discover IDs from splits files, bulk-fetch handedness, persist.
        Returns the meta block of the resulting people.json."""
        ids_needed = self._discover_player_ids()
        if verbose:
            print(f"  Discovered {len(ids_needed):,} unique player IDs across splits files.")

        out_path = self.backfill_root / "people.json"
        existing = self._load_existing(out_path)
        already_have = set(int(pid) for pid in existing.get("players", {}).keys())
        todo = sorted(ids_needed - already_have)
        if verbose:
            print(f"  Already cached: {len(already_have):,}. To fetch: {len(todo):,}.")

        if not todo:
            if verbose:
                print(f"  Nothing to do — people.json is up to date.")
            return existing.get("meta", {})

        players = dict(existing.get("players", {}))
        errors = 0
        n_batches = (len(todo) + self.batch_size - 1) // self.batch_size
        for i, batch in enumerate(self._chunked(todo, self.batch_size), 1):
            fetched = self._fetch_batch(batch)
            if fetched is None:
                errors += len(batch)
                if verbose:
                    print(f"    [{i}/{n_batches}] batch failed ({len(batch)} ids)")
                continue
            for pid, entry in fetched.items():
                players[str(pid)] = entry
            if verbose and (i % 5 == 0 or i == n_batches):
                print(f"    [{i}/{n_batches}] batches done; cached {len(players):,} players")

        meta = {
            "fetched_at": datetime.utcnow().isoformat(),
            "n_players": len(players),
            "n_errors": errors,
        }
        out = {"meta": meta, "players": players}
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, indent=2, default=str))
        if verbose:
            size_kb = out_path.stat().st_size / 1024
            print(
                f"  Wrote {out_path.relative_to(self.backfill_root.parent)} "
                f"({size_kb:.0f} KB; {len(players):,} players, {errors} errors)"
            )
        return meta

    # ---------------- discovery ---------------------------------------

    def _discover_player_ids(self) -> set[int]:
        """Union of every player_id appearing in any season's splits.json."""
        ids: set[int] = set()
        if not self.backfill_root.exists():
            return ids
        for child in self.backfill_root.iterdir():
            if not child.is_dir() or not child.name.isdigit():
                continue
            splits_path = child / "splits.json"
            if not splits_path.exists():
                continue
            try:
                data = json.loads(splits_path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            for group in ("hitting", "pitching"):
                for pid in data.get(group, {}).keys():
                    try:
                        ids.add(int(pid))
                    except ValueError:
                        continue
        return ids

    # ---------------- API fetch --------------------------------------

    def _fetch_batch(self, ids: list[int]) -> dict[int, dict] | None:
        """Bulk-fetch handedness for up to batch_size IDs. Returns
        {player_id: {name, bat_side, pitch_hand}} or None on failure."""
        url = PEOPLE_URL.format(ids=",".join(str(i) for i in ids))
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
                payload = resp.json()
                break
            except requests.RequestException:
                if attempt >= self.max_retries:
                    return None
                time.sleep(1.0 * (2 ** attempt))

        out: dict[int, dict] = {}
        for person in payload.get("people", []):
            pid = person.get("id")
            if pid is None:
                continue
            bat = (person.get("batSide") or {}).get("code")
            pit = (person.get("pitchHand") or {}).get("code")
            out[int(pid)] = {
                "name": person.get("fullName"),
                "bat_side": bat,
                "pitch_hand": pit,
            }
        return out

    # ---------------- IO + utility -----------------------------------

    @staticmethod
    def _load_existing(path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _chunked(items: list[int], size: int) -> Iterable[list[int]]:
        for i in range(0, len(items), size):
            yield items[i:i + size]

    def _throttle(self) -> None:
        if self.request_interval_s <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        wait = self.request_interval_s - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()
