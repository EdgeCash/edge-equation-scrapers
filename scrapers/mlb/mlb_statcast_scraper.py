"""
MLB Statcast Expected-Stats Scraper. EXPERIMENTAL.
==================================================
Pulls per-season expected hitting outcomes (xBA, xSLG, xwOBA) from
Baseball Savant's pre-aggregated leaderboard endpoint. These are the
contact-quality-based "what should have happened" rates derived from
exit velocity + launch angle on every batted ball.

Why xBA/xSLG over AVG/SLG: a hitter putting up .240/.420 on .310/.520
expected is not the same player as one putting up .240/.420 on
.235/.395 expected. The first is unlucky; the second is bad. Over a
full season, xBA correlates ~30% better with NEXT-year actual AVG than
this-year actual AVG does. That's the single biggest free improvement
to a player-prop projection model.

Data source: https://baseballsavant.mlb.com/leaderboard/expected_statistics
- type=batter or type=pitcher
- year=YYYY
- min=N (minimum PAs to include; defaults to 50 to skip tiny-sample
  call-ups while keeping reasonable bench coverage)
- csv=true (returns CSV instead of HTML)

Per-season output: ~30-50 KB JSON keyed by player_id, fields trimmed
to the columns we actually consume.

Output:
    data/backfill/mlb/<season>/statcast_xstats.json
        {
          "meta": {"season": int, "fetched_at": iso, "n_batters": int, "n_pitchers": int},
          "batting": {
            "<player_id>": {"name": str, "pa": int, "bip": int,
                             "ba": float, "xba": float,
                             "slg": float, "xslg": float,
                             "woba": float, "xwoba": float},
            ...
          },
          "pitching": {<player_id>: {... same shape, batters faced ...}}
        }

Idempotent: if a season's statcast_xstats.json already exists, the
scraper skips it. Light: at most a handful of HTTP calls total per
season (one per type), no rate-limit pressure.
"""

from __future__ import annotations

import csv
import io
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable

import requests

LEADERBOARD_URL = (
    "https://baseballsavant.mlb.com/leaderboard/expected_statistics"
    "?type={type}&year={year}&min={minimum}&csv=true"
)

DEFAULT_REQUEST_INTERVAL_S = 1.0  # polite, the site is cloudflare-fronted
DEFAULT_BATTER_MIN = 50          # at least 50 PAs to include
DEFAULT_PITCHER_MIN = 20          # at least 20 batters faced

# Columns we keep — ignore everything else the leaderboard returns.
# Names match the Savant CSV exactly. Values come back as strings; we
# convert to numbers in the parser.
BATTER_KEEP = (
    "last_name, first_name", "player_id", "year", "pa", "bip",
    "ba", "est_ba", "slg", "est_slg", "woba", "est_woba",
)
PITCHER_KEEP = (
    "last_name, first_name", "player_id", "year", "pa", "bip",
    "ba", "est_ba", "slg", "est_slg", "woba", "est_woba",
)


class MLBStatcastScraper:
    """Per-season Statcast expected-stats harvester."""

    def __init__(
        self,
        backfill_root: Path,
        request_interval_s: float = DEFAULT_REQUEST_INTERVAL_S,
        max_retries: int = 2,
        batter_min: int = DEFAULT_BATTER_MIN,
        pitcher_min: int = DEFAULT_PITCHER_MIN,
    ):
        self.backfill_root = Path(backfill_root)
        self.request_interval_s = request_interval_s
        self.max_retries = max_retries
        self.batter_min = batter_min
        self.pitcher_min = pitcher_min
        self._last_request_at = 0.0

    # ---------------- public ---------------------------------------------

    def fetch_seasons(
        self, seasons: Iterable[int], verbose: bool = True,
    ) -> dict[int, dict]:
        report: dict[int, dict] = {}
        for season in seasons:
            if verbose:
                print(f"\n=== Statcast xstats — season {season} ===")
            report[season] = self.fetch_season(season, verbose=verbose)
        return report

    def fetch_season(self, season: int, verbose: bool = True) -> dict:
        season_dir = self.backfill_root / str(season)
        out_path = season_dir / "statcast_xstats.json"

        if out_path.exists():
            if verbose:
                print(f"  Already complete at {out_path.relative_to(self.backfill_root.parent)}; skipping.")
            return {"skipped": True}

        if verbose:
            print(f"  Fetching batter leaderboard (min={self.batter_min})...", flush=True)
        batting = self._fetch_csv(season, "batter", self.batter_min)
        if batting is None:
            return {"error": "fetch_batter_failed"}

        if verbose:
            print(f"  Fetching pitcher leaderboard (min={self.pitcher_min})...", flush=True)
        pitching = self._fetch_csv(season, "pitcher", self.pitcher_min)
        if pitching is None:
            return {"error": "fetch_pitcher_failed"}

        meta = {
            "season": season,
            "fetched_at": datetime.utcnow().isoformat(),
            "n_batters": len(batting),
            "n_pitchers": len(pitching),
        }
        out = {"meta": meta, "batting": batting, "pitching": pitching}
        season_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, indent=2, default=str))
        if verbose:
            size_kb = out_path.stat().st_size / 1024
            print(
                f"  Wrote {out_path.relative_to(self.backfill_root.parent)} "
                f"({size_kb:.0f} KB; batters={meta['n_batters']}, "
                f"pitchers={meta['n_pitchers']})"
            )
        return meta

    # ---------------- fetch + parse --------------------------------------

    def _fetch_csv(
        self, season: int, type_: str, minimum: int,
    ) -> dict[str, dict] | None:
        url = LEADERBOARD_URL.format(type=type_, year=season, minimum=minimum)
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                resp = requests.get(url, timeout=60, headers={
                    # Savant returns 403 for default urllib UA in some regions.
                    "User-Agent": "edge-equation-bot/1.0 (research)",
                })
                resp.raise_for_status()
                text = resp.text
                break
            except requests.RequestException:
                if attempt >= self.max_retries:
                    return None
                time.sleep(2.0 * (2 ** attempt))

        return self._parse_csv(text)

    @staticmethod
    def _parse_csv(text: str) -> dict[str, dict]:
        """Parse Savant CSV → {player_id: {trimmed fields}}.

        Player names come as 'Last, First' in a single column called
        `last_name, first_name`. We split on the LAST comma so first
        names with embedded commas stay intact.
        """
        out: dict[str, dict] = {}
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            pid = (row.get("player_id") or "").strip()
            if not pid or not pid.isdigit():
                continue
            name_raw = (row.get("last_name, first_name") or "").strip()
            if "," in name_raw:
                last, first = name_raw.split(",", 1)
                name = f"{first.strip()} {last.strip()}"
            else:
                name = name_raw
            out[pid] = {
                "name": name,
                "pa": _to_int(row.get("pa")),
                "bip": _to_int(row.get("bip")),
                "ba": _to_float(row.get("ba")),
                "xba": _to_float(row.get("est_ba")),
                "slg": _to_float(row.get("slg")),
                "xslg": _to_float(row.get("est_slg")),
                "woba": _to_float(row.get("woba")),
                "xwoba": _to_float(row.get("est_woba")),
            }
        return out

    # ---------------- throttle ------------------------------------------

    def _throttle(self) -> None:
        if self.request_interval_s <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        wait = self.request_interval_s - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()


def _to_int(v) -> int:
    if v is None or v == "":
        return 0
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _to_float(v) -> float | None:
    """Savant CSV uses leading dot for sub-1 rates (e.g. '.310'). None
    if blank or unparseable."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
