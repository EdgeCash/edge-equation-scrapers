"""
MLB Odds Scraper
================
Pulls live moneyline / run-line / total prices for today's MLB slate.

Sources (in order):
    1. The Odds API (the-odds-api.com)   — preferred, multi-book, requires
       a free API key in env var ODDS_API_KEY.
    2. DraftKings public sportsbook JSON — fallback, single book, no key
       required, fragile (DK can change endpoints without notice).

Both sources are normalized into the same shape so callers don't have
to care which one fired:

    {
      "fetched_at": "...",
      "source": "the-odds-api" | "draftkings",
      "games": [
         {
           "away_team": "NYY", "home_team": "LAD",
           "commence_time": "2026-05-02T23:05:00Z",
           "moneyline": {
              "away": {"decimal": 2.85, "american": 185, "book": "draftkings"},
              "home": {"decimal": 1.45, "american": -222, "book": "fanduel"}
           },
           "run_line": [
              {"team": "home", "point": -1.5, "decimal": 1.95, "american": -105, "book": "..."},
              {"team": "away", "point":  1.5, "decimal": 1.95, "american": -105, "book": "..."}
           ],
           "totals": [
              {"point": 8.5,
               "over":  {"decimal": 1.91, "american": -110, "book": "..."},
               "under": {"decimal": 1.91, "american": -110, "book": "..."}}
           ]
         }
      ]
    }

For each market, the price returned is the BEST (highest decimal) price
across all bookmakers seen, so the consumer can shop the line.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Iterable

import requests

from global_utils.quota_log import log_quota


# Full team name -> 3-letter code (matches scrapers/mlb/mlb_game_scraper.py).
TEAM_NAME_TO_CODE = {
    "Arizona Diamondbacks": "AZ",
    "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL",
    "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHC",
    "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN",
    "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL",
    "Detroit Tigers": "DET",
    "Houston Astros": "HOU",
    "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA",
    "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN",
    "New York Mets": "NYM",
    "New York Yankees": "NYY",
    "Athletics": "ATH",
    "Oakland Athletics": "ATH",
    "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SD",
    "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA",
    "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB",
    "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR",
    "Washington Nationals": "WSH",
}

ODDS_API_URL = "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds"
DK_EVENTGROUP_URL = "https://sportsbook-nash.draftkings.com/sites/US-SB/api/v5/eventgroups/84240"


def decimal_to_american(decimal: float) -> int:
    """Convert decimal odds to American (+/-) form, rounded to nearest int."""
    if decimal is None or decimal <= 1.0:
        return 0
    if decimal >= 2.0:
        return round((decimal - 1) * 100)
    return round(-100 / (decimal - 1))


def _team_code(name: str) -> str | None:
    return TEAM_NAME_TO_CODE.get(name)


def _better_price(existing: dict | None, candidate: dict) -> dict:
    """Return whichever price has the higher decimal odds."""
    if existing is None:
        return candidate
    if candidate["decimal"] > existing["decimal"]:
        return candidate
    return existing


# Quota logging extracted to global_utils/quota_log.py so NFL/NCAAF
# (and any other sport) can share the implementation. Imported above.


class MLBOddsScraper:
    """Fetch and normalize MLB game-level lines from a free source."""

    def __init__(
        self,
        api_key: str | None = None,
        quota_log_path: Path | None = None,
    ):
        self.api_key = api_key or os.environ.get("ODDS_API_KEY")
        self.quota_log_path = quota_log_path

    # ---------------- public ---------------------------------------------

    def fetch(self) -> dict:
        """Try The Odds API, fall back to DraftKings, fall back to empty."""
        if self.api_key:
            try:
                return self._fetch_odds_api()
            except Exception as e:
                print(f"  Odds API failed ({type(e).__name__}: {e}); falling back to DK.")

        try:
            return self._fetch_draftkings()
        except Exception as e:
            print(f"  DraftKings fetch failed ({type(e).__name__}: {e}); returning empty.")
            return {
                "fetched_at": datetime.utcnow().isoformat() + "Z",
                "source": "none",
                "games": [],
            }

    # ---------------- the-odds-api.com -----------------------------------

    def _fetch_odds_api(self) -> dict:
        params = {
            "apiKey": self.api_key,
            "regions": "us",
            "markets": "h2h,spreads,totals",
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        }
        resp = requests.get(ODDS_API_URL, params=params, timeout=30)
        resp.raise_for_status()
        if self.quota_log_path is not None:
            log_quota(self.quota_log_path, resp.headers, "baseball_mlb/odds")
        events = resp.json()

        games = []
        for ev in events:
            away_code = _team_code(ev.get("away_team", ""))
            home_code = _team_code(ev.get("home_team", ""))
            if not away_code or not home_code:
                continue

            ml: dict = {}
            rl: list[dict] = []
            totals_by_line: dict[float, dict] = {}

            for bk in ev.get("bookmakers", []):
                book = bk.get("key")
                for market in bk.get("markets", []):
                    mk = market.get("key")
                    outs = market.get("outcomes", [])
                    if mk == "h2h":
                        for o in outs:
                            side = "away" if o.get("name") == ev["away_team"] else "home"
                            ml[side] = _better_price(ml.get(side), {
                                "decimal": o["price"],
                                "american": decimal_to_american(o["price"]),
                                "book": book,
                            })
                    elif mk == "spreads":
                        for o in outs:
                            side = "away" if o.get("name") == ev["away_team"] else "home"
                            rl.append({
                                "team": side,
                                "point": o.get("point"),
                                "decimal": o["price"],
                                "american": decimal_to_american(o["price"]),
                                "book": book,
                            })
                    elif mk == "totals":
                        for o in outs:
                            line = o.get("point")
                            if line is None:
                                continue
                            slot = totals_by_line.setdefault(line, {"point": line})
                            side = "over" if o.get("name", "").lower() == "over" else "under"
                            slot[side] = _better_price(slot.get(side), {
                                "decimal": o["price"],
                                "american": decimal_to_american(o["price"]),
                                "book": book,
                            })

            games.append({
                "away_team": away_code,
                "home_team": home_code,
                "commence_time": ev.get("commence_time"),
                "moneyline": ml,
                "run_line": _best_run_line(rl),
                "totals": sorted(totals_by_line.values(), key=lambda t: t["point"]),
            })

        return {
            "fetched_at": datetime.utcnow().isoformat() + "Z",
            "source": "the-odds-api",
            "games": games,
        }

    # ---------------- DraftKings fallback --------------------------------

    def _fetch_draftkings(self) -> dict:
        resp = requests.get(
            DK_EVENTGROUP_URL,
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0 (Edge Equation odds fetcher)"},
        )
        resp.raise_for_status()
        data = resp.json()

        events = (
            data.get("eventGroup", {})
                .get("events", [])
        )
        offer_categories = (
            data.get("eventGroup", {})
                .get("offerCategories", [])
        )

        # DK groups offers by event id; collect them up front.
        offers_by_event: dict[str, list[dict]] = {}
        for cat in offer_categories:
            for sub in cat.get("offerSubcategoryDescriptors", []):
                for offer_group in sub.get("offerSubcategory", {}).get("offers", []):
                    for offer in offer_group:
                        eid = str(offer.get("eventId"))
                        offers_by_event.setdefault(eid, []).append(offer)

        games = []
        for ev in events:
            away_name = ev.get("awayTeamName") or ev.get("teamName2")
            home_name = ev.get("homeTeamName") or ev.get("teamName1")
            away_code = _team_code(away_name or "")
            home_code = _team_code(home_name or "")
            if not away_code or not home_code:
                continue

            ml: dict = {}
            rl: list[dict] = []
            totals_by_line: dict[float, dict] = {}

            for offer in offers_by_event.get(str(ev.get("eventId")), []):
                label = (offer.get("label") or "").lower()
                outcomes = offer.get("outcomes", [])

                if "moneyline" in label:
                    for o in outcomes:
                        side = "away" if o.get("label") == away_name else "home"
                        dec = _dk_decimal(o)
                        if dec is None:
                            continue
                        ml[side] = _better_price(ml.get(side), {
                            "decimal": dec,
                            "american": decimal_to_american(dec),
                            "book": "draftkings",
                        })
                elif "run line" in label or "spread" in label:
                    for o in outcomes:
                        side = "away" if o.get("label") == away_name else "home"
                        dec = _dk_decimal(o)
                        line = _dk_line(o)
                        if dec is None or line is None:
                            continue
                        rl.append({
                            "team": side,
                            "point": line,
                            "decimal": dec,
                            "american": decimal_to_american(dec),
                            "book": "draftkings",
                        })
                elif "total" in label:
                    for o in outcomes:
                        dec = _dk_decimal(o)
                        line = _dk_line(o)
                        if dec is None or line is None:
                            continue
                        slot = totals_by_line.setdefault(line, {"point": line})
                        side = "over" if (o.get("label") or "").lower().startswith("o") else "under"
                        slot[side] = _better_price(slot.get(side), {
                            "decimal": dec,
                            "american": decimal_to_american(dec),
                            "book": "draftkings",
                        })

            games.append({
                "away_team": away_code,
                "home_team": home_code,
                "commence_time": ev.get("startDate"),
                "moneyline": ml,
                "run_line": _best_run_line(rl),
                "totals": sorted(totals_by_line.values(), key=lambda t: t["point"]),
            })

        return {
            "fetched_at": datetime.utcnow().isoformat() + "Z",
            "source": "draftkings",
            "games": games,
        }

    # ---------------- lookup ---------------------------------------------

    @staticmethod
    def find_game(odds: dict, away: str, home: str) -> dict | None:
        for g in odds.get("games", []):
            if g["away_team"] == away and g["home_team"] == home:
                return g
        return None


def _dk_decimal(outcome: dict) -> float | None:
    """Pull a decimal price from a DK outcome (DK gives both forms)."""
    dec = outcome.get("oddsDecimal")
    if dec is not None:
        try:
            return float(dec)
        except (TypeError, ValueError):
            return None
    am = outcome.get("oddsAmerican")
    if am is None:
        return None
    try:
        am = int(am)
    except (TypeError, ValueError):
        return None
    return round(1 + (am / 100 if am > 0 else 100 / -am), 4)


def _dk_line(outcome: dict) -> float | None:
    line = outcome.get("line")
    if line is None:
        return None
    try:
        return float(line)
    except (TypeError, ValueError):
        return None


def _best_run_line(rows: Iterable[dict]) -> list[dict]:
    """Collapse multiple book offers at the same (team, point) to the best price."""
    best: dict[tuple[str, float], dict] = {}
    for r in rows:
        key = (r["team"], r["point"])
        existing = best.get(key)
        if existing is None or r["decimal"] > existing["decimal"]:
            best[key] = r
    return sorted(best.values(), key=lambda r: (r["team"], r["point"]))


if __name__ == "__main__":
    import json
    scraper = MLBOddsScraper()
    out = scraper.fetch()
    print(f"Source: {out['source']}  |  Games: {len(out['games'])}")
    if out["games"]:
        print(json.dumps(out["games"][0], indent=2))
