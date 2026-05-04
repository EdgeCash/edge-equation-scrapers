"""
The Odds API — Generic Harvester
================================
Cross-sport helper that pulls market lines from The Odds API
(`api.the-odds-api.com`). Supports both the LIVE endpoint
(`/v4/sports/{sport_key}/odds`) and the HISTORICAL endpoint
(`/v4/historical/sports/{sport_key}/odds`).

Used by per-sport thin wrappers (NHL/NBA/WNBA odds scrapers) — each
wrapper supplies the `sport_key` and a team-name -> abbreviation map
so output joins cleanly against ESPN game-results.

Output shape (one entry per game):
    {
      "fetched_at": "...",
      "snapshot_at": "...",            # historical only — actual snapshot timestamp
      "source": "odds-api-live" | "odds-api-historical",
      "sport_key": "icehockey_nhl",
      "games": [
         {
           "event_id": "...",          # The Odds API event id
           "commence_time": "...",
           "away_team": "BOS", "home_team": "NYR",
           "lines": [
             {
               "provider": "draftkings",
               "h2h":    {"home": -120, "away": +110},      # american odds
               "spread": {"home": {"point": -1.5, "price": -110},
                          "away": {"point": +1.5, "price": -110}},
               "totals": {"point": 6.5, "over": -105, "under": -115}
             }, ...
           ]
         }
      ]
    }

Credit cost (May 2026, $30/mo plan): live = 1 credit per call;
historical = 10 credits per call. Daily live harvest is essentially
free (~3 credits/day across NHL/NBA/WNBA); historical bulk pulls
should be budgeted carefully.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

import requests

from global_utils.quota_log import log_quota


ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4"

# The Odds API rate-limits at the credit-budget level (e.g. 20K/mo on
# the $30 tier). Per-second throttling isn't strictly required, but a
# small floor keeps us from hammering historical pulls.
DEFAULT_REQUEST_INTERVAL_S = 0.5


@dataclass(frozen=True)
class NormalizedLine:
    provider: str
    h2h_home: int | None
    h2h_away: int | None
    spread_home_point: float | None
    spread_home_price: int | None
    spread_away_point: float | None
    spread_away_price: int | None
    total_point: float | None
    total_over: int | None
    total_under: int | None


def decimal_to_american(decimal: float | None) -> int | None:
    """Convert decimal odds to American (+/-) form. Mirrors the helper
    in scrapers/mlb/mlb_odds_scraper.py — duplicated here to keep the
    odds-api package self-contained."""
    if decimal is None or decimal <= 1.0:
        return None
    if decimal >= 2.0:
        return round((decimal - 1) * 100)
    return round(-100 / (decimal - 1))


class OddsApiHarvester:
    """Pulls Odds API responses and normalizes them.

    The harvester is sport-agnostic: callers pass `sport_key` (e.g.
    "icehockey_nhl") and `team_name_to_code` (full name -> 3-letter
    abbreviation) when invoking fetch methods.
    """

    def __init__(
        self,
        api_key: str,
        quota_log_path: Path | None = None,
        request_interval_s: float = DEFAULT_REQUEST_INTERVAL_S,
        max_retries: int = 2,
    ):
        if not api_key:
            raise ValueError("api_key is required")
        self.api_key = api_key.strip()
        self.quota_log_path = quota_log_path
        self.request_interval_s = request_interval_s
        self.max_retries = max_retries
        self._last_request_at = 0.0

    # ---------------- public ---------------------------------------------

    def fetch_live(
        self,
        sport_key: str,
        team_name_to_code: dict[str, str],
        regions: str = "us",
        markets: str = "h2h,spreads,totals",
    ) -> dict:
        """Fetch current/upcoming odds for a sport. 1 credit per call."""
        url = f"{ODDS_API_BASE_URL}/sports/{sport_key}/odds"
        params = {
            "apiKey": self.api_key,
            "regions": regions,
            "markets": markets,
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        }
        resp = self._request(url, params, endpoint=f"{sport_key}/odds")
        events = resp.json()
        return {
            "fetched_at": datetime.utcnow().isoformat() + "Z",
            "source": "odds-api-live",
            "sport_key": sport_key,
            "games": [
                self._normalize_event(ev, team_name_to_code) for ev in events
            ],
        }

    def fetch_historical(
        self,
        sport_key: str,
        team_name_to_code: dict[str, str],
        snapshot_iso: str,
        regions: str = "us",
        markets: str = "h2h,spreads,totals",
    ) -> dict:
        """Fetch the snapshot closest to `snapshot_iso` (UTC ISO 8601).
        10 credits per call.

        The Odds API returns the closest available snapshot at or
        before the requested timestamp. The actual snapshot timestamp
        is preserved in `snapshot_at`."""
        url = f"{ODDS_API_BASE_URL}/historical/sports/{sport_key}/odds"
        params = {
            "apiKey": self.api_key,
            "regions": regions,
            "markets": markets,
            "oddsFormat": "decimal",
            "dateFormat": "iso",
            "date": snapshot_iso,
        }
        resp = self._request(
            url, params, endpoint=f"historical/{sport_key}/odds",
        )
        payload = resp.json()
        # Historical endpoint wraps in {timestamp, previous_timestamp,
        # next_timestamp, data: [...events...]}.
        if isinstance(payload, dict) and "data" in payload:
            events = payload.get("data") or []
            snapshot_at = payload.get("timestamp")
        else:
            events = payload if isinstance(payload, list) else []
            snapshot_at = None
        return {
            "fetched_at": datetime.utcnow().isoformat() + "Z",
            "snapshot_at": snapshot_at,
            "source": "odds-api-historical",
            "sport_key": sport_key,
            "games": [
                self._normalize_event(ev, team_name_to_code) for ev in events
            ],
        }

    def fetch_historical_range(
        self,
        sport_key: str,
        team_name_to_code: dict[str, str],
        snapshots_iso: Iterable[str],
        progress_cb: Callable[[int, int, dict], None] | None = None,
    ) -> list[dict]:
        """Fetch a sequence of historical snapshots; returns one entry
        per snapshot. `progress_cb(i, total, snapshot)` fires after
        each successful fetch — useful for verbose backfill loops.

        Throttled and retry-aware (same as the underlying single-call
        method)."""
        snapshots = list(snapshots_iso)
        total = len(snapshots)
        out: list[dict] = []
        for i, ts in enumerate(snapshots, 1):
            try:
                snap = self.fetch_historical(sport_key, team_name_to_code, ts)
            except requests.RequestException:
                # Skip individual day failures; caller can re-run to
                # fill gaps. Do NOT abort the whole pull.
                continue
            out.append(snap)
            if progress_cb is not None:
                progress_cb(i, total, snap)
        return out

    # ---------------- internals ------------------------------------------

    def _request(self, url: str, params: dict, endpoint: str) -> requests.Response:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                resp = requests.get(url, params=params, timeout=60)
                if self.quota_log_path is not None:
                    log_quota(self.quota_log_path, resp.headers, endpoint)
                resp.raise_for_status()
                return resp
            except requests.RequestException as e:
                last_exc = e
                if attempt >= self.max_retries:
                    break
                time.sleep(2.0 * (2 ** attempt))
        # Re-raise so callers can decide whether to skip or abort.
        assert last_exc is not None
        raise last_exc

    def _throttle(self) -> None:
        if self.request_interval_s <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        wait = self.request_interval_s - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    @staticmethod
    def _normalize_event(
        event: dict, team_name_to_code: dict[str, str],
    ) -> dict:
        away_name = event.get("away_team", "")
        home_name = event.get("home_team", "")
        away_code = team_name_to_code.get(away_name, away_name)
        home_code = team_name_to_code.get(home_name, home_name)

        lines: list[dict] = []
        for bk in event.get("bookmakers", []) or []:
            line: dict = {"provider": bk.get("key")}
            for market in bk.get("markets", []) or []:
                mk = market.get("key")
                outs = market.get("outcomes", []) or []
                if mk == "h2h":
                    h2h: dict = {}
                    for o in outs:
                        side = "home" if o.get("name") == home_name else "away"
                        h2h[side] = decimal_to_american(o.get("price"))
                    line["h2h"] = h2h
                elif mk == "spreads":
                    spread: dict = {}
                    for o in outs:
                        side = "home" if o.get("name") == home_name else "away"
                        spread[side] = {
                            "point": _to_float(o.get("point")),
                            "price": decimal_to_american(o.get("price")),
                        }
                    line["spread"] = spread
                elif mk == "totals":
                    totals: dict = {"point": None, "over": None, "under": None}
                    for o in outs:
                        side = (o.get("name") or "").lower()  # "Over"/"Under"
                        if side == "over":
                            totals["over"] = decimal_to_american(o.get("price"))
                            totals["point"] = _to_float(o.get("point"))
                        elif side == "under":
                            totals["under"] = decimal_to_american(o.get("price"))
                            if totals["point"] is None:
                                totals["point"] = _to_float(o.get("point"))
                    line["totals"] = totals
            lines.append(line)

        return {
            "event_id": event.get("id"),
            "commence_time": event.get("commence_time"),
            "away_team": away_code,
            "home_team": home_code,
            "away_name": away_name,
            "home_name": home_name,
            "lines": lines,
        }


def _to_float(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
