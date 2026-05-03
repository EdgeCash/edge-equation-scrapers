"""
NCAAF Historical Lines Scraper (CFBD)
=====================================
Pulls per-game closing + opening lines from collegefootballdata.com
across multiple sportsbooks. Real closing-line data — a competitive
advantage we don't have for MLB, where we only see live odds via the
Odds API.

Why this matters for the backtest:
- For MLB we synthesize gating implied lines from our own model
  ("did we beat -110 fair odds?"). It's a useful check but it doesn't
  validate against what the market actually closed at.
- For NCAAF, with CFBD lines, the backtest can compare our projected
  spread/total/ML to the ACTUAL closing prices at DraftKings, FanDuel,
  Bovada, etc. CLV becomes computable retroactively across 5 seasons
  before we even publish a single live pick.

Data source: https://api.collegefootballdata.com/lines
Authentication: Bearer token. Get a free key at
https://collegefootballdata.com/key. Pass via constructor or
`CFBD_API_KEY` env var.

Per-season volume: ~1000 games × ~7 books = ~7000 line entries per
season. The /lines endpoint returns all games for a (season,
seasonType) combo in one response (~5-10 MB JSON). Two calls per
season (regular + postseason). Total: 10 calls for a 5-season pull —
nowhere near the 200 calls/min free-tier limit.

Output:
    data/backfill/ncaaf/<season>/lines.json
        [
          {
            "game_id": int,            # CFBD-assigned, matches ESPN id
            "season": int,
            "week": int,
            "season_type": str,        # "regular" | "postseason"
            "start_date": str,
            "home_team": str,
            "away_team": str,
            "home_score": int|None,
            "away_score": int|None,
            "lines": [
              {"provider": str,
               "spread_close": float|None,
               "spread_open":  float|None,
               "total_close":  float|None,
               "total_open":   float|None,
               "home_ml": int|None,
               "away_ml": int|None}, ...
            ]
          }, ...
        ]

Idempotent: if the season's lines.json already exists, the scraper
skips the API call.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Iterable

import requests

CFBD_BASE_URL = "https://api.collegefootballdata.com"

# 200 req/min on the free tier; 0.5s interval keeps us comfortably
# under that even when running multiple seasons in a tight loop.
DEFAULT_REQUEST_INTERVAL_S = 0.5


class CFBDLinesScraper:
    """Per-season historical lines harvester."""

    def __init__(
        self,
        output_root: Path,
        api_key: str | None = None,
        request_interval_s: float = DEFAULT_REQUEST_INTERVAL_S,
        max_retries: int = 2,
    ):
        self.output_root = Path(output_root)
        # Allow constructor key, fall back to env. Fail fast at first
        # call rather than constructor so a missing key doesn't surface
        # only when the workflow is mid-run.
        self.api_key = api_key or os.environ.get("CFBD_API_KEY")
        self.request_interval_s = request_interval_s
        self.max_retries = max_retries
        self._last_request_at = 0.0

    # ---------------- public ---------------------------------------------

    def fetch_seasons(
        self,
        seasons: Iterable[int],
        include_postseason: bool = True,
        verbose: bool = True,
    ) -> dict[int, dict]:
        """Fetch lines for each season. Returns a per-season report."""
        report: dict[int, dict] = {}
        for season in seasons:
            if verbose:
                print(f"\n=== NCAAF Lines — season {season} ===")
            entry = self.fetch_season(
                season,
                include_postseason=include_postseason,
                verbose=verbose,
            )
            report[season] = entry
        return report

    def fetch_season(
        self,
        season: int,
        include_postseason: bool = True,
        verbose: bool = True,
    ) -> dict:
        """Fetch + persist all lines for one season. Idempotent."""
        path = self.output_root / str(season) / "lines.json"
        if path.exists():
            if verbose:
                rel = path.relative_to(self.output_root.parent)
                print(f"  Lines already cached at {rel}; skipping.")
            return {"skipped": True}

        if not self.api_key:
            msg = "CFBD_API_KEY not set; cannot fetch lines."
            if verbose:
                print(f"  {msg}")
            return {"error": msg}

        all_records: list[dict] = []

        if verbose:
            print(f"  Fetching regular-season lines...")
        regular = self._fetch_endpoint(season, "regular")
        if regular is None:
            return {"error": "fetch_regular_failed"}
        all_records.extend(regular)
        if verbose:
            print(f"    {len(regular)} regular-season game-line records")

        if include_postseason:
            if verbose:
                print(f"  Fetching postseason lines...")
            post = self._fetch_endpoint(season, "postseason")
            if post is None:
                if verbose:
                    print(f"    postseason fetch failed; proceeding with regular only")
            else:
                all_records.extend(post)
                if verbose:
                    print(f"    {len(post)} postseason game-line records")

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(all_records, indent=2, default=str))

        # Quick stats: how many games actually have lines, and how many
        # books on average. Useful for sanity-checking coverage.
        n_with_lines = sum(1 for r in all_records if r.get("lines"))
        avg_books = (
            sum(len(r.get("lines") or []) for r in all_records) / n_with_lines
            if n_with_lines else 0.0
        )
        size_kb = path.stat().st_size / 1024
        if verbose:
            rel = path.relative_to(self.output_root.parent)
            print(
                f"  Wrote {rel} ({size_kb:.0f} KB; "
                f"{len(all_records)} games, "
                f"{n_with_lines} have lines, "
                f"avg {avg_books:.1f} books/game)"
            )
        return {
            "n_games": len(all_records),
            "n_with_lines": n_with_lines,
            "avg_books_per_game": round(avg_books, 1),
            "size_kb": round(size_kb, 1),
        }

    # ---------------- HTTP fetch -----------------------------------------

    def _fetch_endpoint(self, season: int, season_type: str) -> list[dict] | None:
        url = f"{CFBD_BASE_URL}/lines"
        params = {"year": season, "seasonType": season_type}
        headers = {"Authorization": f"Bearer {self.api_key}"}

        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                resp = requests.get(url, params=params, headers=headers, timeout=60)
                resp.raise_for_status()
                payload = resp.json()
                break
            except requests.RequestException:
                if attempt >= self.max_retries:
                    return None
                time.sleep(2.0 * (2 ** attempt))

        return [self._normalize_record(r, season_type) for r in payload]

    @staticmethod
    def _normalize_record(raw: dict, season_type: str) -> dict:
        """Trim CFBD's response to the fields we'll actually consume.

        CFBD uses both `id`/`gameId` and `season` keys; we keep both as
        `game_id` (int) to match the ESPN ids in games.json. Lines come
        as a list of provider blocks; we keep close + open spread/total
        plus moneylines.
        """
        lines = raw.get("lines") or []
        normalized_lines = []
        for ln in lines:
            normalized_lines.append({
                "provider": ln.get("provider"),
                "spread_close": _to_float(ln.get("spread")),
                "spread_open": _to_float(ln.get("spreadOpen")),
                "total_close": _to_float(ln.get("overUnder")),
                "total_open": _to_float(ln.get("overUnderOpen")),
                "home_ml": _to_int(ln.get("homeMoneyline")),
                "away_ml": _to_int(ln.get("awayMoneyline")),
                # Keep the formatted_spread for diagnostics (e.g. so the
                # workflow log can show "Florida State -10.5" rather
                # than just -10.5 against an ambiguous side).
                "formatted_spread": ln.get("formattedSpread"),
            })
        return {
            "game_id": raw.get("id") or raw.get("gameId"),
            "season": raw.get("season"),
            "week": raw.get("week"),
            "season_type": season_type,
            "start_date": raw.get("startDate"),
            "home_team": raw.get("homeTeam"),
            "away_team": raw.get("awayTeam"),
            "home_score": _to_int(raw.get("homeScore")),
            "away_score": _to_int(raw.get("awayScore")),
            "lines": normalized_lines,
        }

    # ---------------- throttle ------------------------------------------

    def _throttle(self) -> None:
        if self.request_interval_s <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        wait = self.request_interval_s - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()


def _to_int(v) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _to_float(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
