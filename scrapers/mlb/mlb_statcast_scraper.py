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

        season_dir.mkdir(parents=True, exist_ok=True)

        if verbose:
            print(f"  Fetching batter leaderboard (min={self.batter_min})...", flush=True)
        batting = self._fetch_csv(
            season, "batter", self.batter_min,
            raw_dump_path=season_dir / "_statcast_batter_raw.csv",
            verbose=verbose,
        )
        if batting is None:
            return {"error": "fetch_batter_failed"}

        if verbose:
            print(f"  Fetching pitcher leaderboard (min={self.pitcher_min})...", flush=True)
        pitching = self._fetch_csv(
            season, "pitcher", self.pitcher_min,
            raw_dump_path=season_dir / "_statcast_pitcher_raw.csv",
            verbose=verbose,
        )
        if pitching is None:
            return {"error": "fetch_pitcher_failed"}

        meta = {
            "season": season,
            "fetched_at": datetime.utcnow().isoformat(),
            "n_batters": len(batting),
            "n_pitchers": len(pitching),
        }
        out = {"meta": meta, "batting": batting, "pitching": pitching}
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
        raw_dump_path: Path | None = None,
        verbose: bool = True,
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

        # Dump the raw response BEFORE parsing — if parsing fails or
        # returns a tiny number of rows, the raw CSV is the first thing
        # we want to inspect for debugging.
        if raw_dump_path is not None:
            try:
                raw_dump_path.write_text(text)
            except OSError:
                pass

        parsed = self._parse_csv(text)

        # Log the response shape so the workflow log captures evidence
        # whether parsing went sideways. Loud diagnostics on first call
        # of each season — that's the cheapest forensic data we can grab.
        if verbose:
            first_line = text.split("\n", 1)[0][:500] if text else ""
            print(f"    response: {len(text):,} chars; "
                  f"first line: {first_line!r}")
            print(f"    parsed: {len(parsed):,} rows")

        return parsed

    @staticmethod
    def _parse_csv(text: str) -> dict[str, dict]:
        """Parse Savant CSV → {player_id: {trimmed fields}}.

        Two header forms in the wild:
          A. Quoted: `"last_name, first_name",player_id,year,pa,...`
             — DictReader sees one column "last_name, first_name".
          B. Unquoted: `last_name, first_name,player_id,year,pa,...`
             — DictReader splits into TWO header columns ("last_name"
                and " first_name"). When the data row's "Judge, Aaron"
                is quoted, the data has one fewer column than the
                header and EVERY field shifts by one column.

        Rather than guess which form we got, we use a positional
        parser. We map header names to column INDICES, find the
        player_id column, and read each row by index. To handle the
        unquoted-header case we ALSO check whether a row has fewer
        columns than the header — in which case we shift the index
        lookups by 1 for that row.
        """
        if not text or len(text) < 50:
            return {}

        # csv.reader handles quoted fields with embedded commas correctly;
        # we just need to map header columns to indices ourselves.
        rows = list(csv.reader(io.StringIO(text)))
        if not rows:
            return {}

        header = rows[0]
        # Strip whitespace and BOM that Savant occasionally prepends.
        header = [h.strip().lstrip("﻿") for h in header]

        # Locate the columns we care about. Tolerate the unquoted-header
        # case by treating "last_name" + " first_name" as a single name
        # column at the same index as "last_name".
        def find_idx(*names):
            for n in names:
                if n in header:
                    return header.index(n)
            return None

        idx_player = find_idx("player_id")
        idx_year = find_idx("year")
        idx_pa = find_idx("pa")
        idx_bip = find_idx("bip")
        idx_ba = find_idx("ba")
        idx_xba = find_idx("est_ba")
        idx_slg = find_idx("slg")
        idx_xslg = find_idx("est_slg")
        idx_woba = find_idx("woba")
        idx_xwoba = find_idx("est_woba")
        idx_name_combined = find_idx("last_name, first_name")
        idx_last = find_idx("last_name")
        idx_first = find_idx("first_name")

        if idx_player is None:
            return {}

        # Detect unquoted-header form: header has the split last_name +
        # first_name pair AND no combined column. Data rows in that case
        # have one fewer column than header, so positional reads need to
        # account for the shift on a per-row basis (any row where the
        # name field DOES contain a comma will be quoted as one field).
        unquoted_header = (
            idx_name_combined is None
            and idx_last is not None
            and idx_first is not None
        )
        n_header_cols = len(header)

        out: dict[str, dict] = {}
        for row in rows[1:]:
            if not row:
                continue

            # If header was unquoted, a row whose name contained a comma
            # came back as ONE quoted field, so the row has one fewer
            # column than the header. Detect by length; shift indices
            # right by 1 for those rows when reading anything past the
            # name column.
            shift = 0
            if unquoted_header and len(row) == n_header_cols - 1:
                shift = 1

            def get(idx, *, after_name=True):
                """Read a field by header index, applying the shift if
                this row used the unquoted-name collapsing form. The
                name column itself is NEVER shifted; columns AFTER the
                name column shift left by 1 in the data row."""
                if idx is None:
                    return None
                if shift and after_name and idx > (idx_last or 0):
                    real = idx - shift
                else:
                    real = idx
                if real < 0 or real >= len(row):
                    return None
                return row[real]

            pid = (get(idx_player) or "").strip()
            if not pid or not pid.isdigit():
                continue

            # Name reconstruction: prefer the combined column, fall back
            # to last+first, fall back to whatever the first column held.
            if idx_name_combined is not None:
                name_raw = (get(idx_name_combined, after_name=False) or "").strip()
                if "," in name_raw:
                    last, first = name_raw.split(",", 1)
                    name = f"{first.strip()} {last.strip()}"
                else:
                    name = name_raw
            elif unquoted_header:
                # In the unquoted-header form the data row's first field
                # holds the entire "Last, First" string (it was quoted).
                last_first = row[0] if row else ""
                if "," in last_first:
                    last, first = last_first.split(",", 1)
                    name = f"{first.strip()} {last.strip()}"
                else:
                    name = last_first
            else:
                name = ""

            out[pid] = {
                "name": name,
                "pa": _to_int(get(idx_pa)),
                "bip": _to_int(get(idx_bip)),
                "ba": _to_float(get(idx_ba)),
                "xba": _to_float(get(idx_xba)),
                "slg": _to_float(get(idx_slg)),
                "xslg": _to_float(get(idx_xslg)),
                "woba": _to_float(get(idx_woba)),
                "xwoba": _to_float(get(idx_xwoba)),
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
