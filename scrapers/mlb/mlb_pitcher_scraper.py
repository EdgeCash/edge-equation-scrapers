"""
MLB Pitcher Scraper
===================
Fetches today's probable starting pitchers from statsapi.mlb.com and
each pitcher's current-season stats, then derives a per-pitcher quality
factor used by the projection model to scale the opposing offense.

Quality factor (multiplicative, 1.0 = league average):
    weighted_era = (era * ip + LEAGUE_ERA * IP_PRIOR) / (ip + IP_PRIOR)
    factor       = weighted_era / LEAGUE_ERA   clamped to [0.70, 1.30]

A factor of 0.85 means the pitcher suppresses opposing run scoring 15%
below league average. The IP-based shrinkage prior keeps a pitcher with
6 IP and a 1.50 ERA from being projected as the next Bob Gibson.

Usage:
    scraper = MLBPitcherScraper(season=2026)
    sp_map  = scraper.fetch_factors_for_slate(slate)   # game_pk -> SP dicts
"""

from __future__ import annotations

import requests

BASE_URL = "https://statsapi.mlb.com/api/v1"

LEAGUE_ERA = 4.20            # rough MLB average ERA
LEAGUE_WHIP = 1.30
IP_PRIOR = 50.0              # ghost innings of league-average performance
MIN_IP_FOR_SIGNAL = 5.0      # below this, factor falls back to 1.0
FACTOR_MIN = 0.70
FACTOR_MAX = 1.30


def _ip_to_float(ip_str: str | float | int | None) -> float:
    """MLB API returns IP as a string like '78.1' meaning 78 1/3 innings."""
    if ip_str is None or ip_str == "":
        return 0.0
    if isinstance(ip_str, (int, float)):
        return float(ip_str)
    try:
        whole, _, frac = str(ip_str).partition(".")
        thirds = {"": 0, "0": 0, "1": 1 / 3, "2": 2 / 3}.get(frac, 0)
        return float(whole) + thirds
    except (TypeError, ValueError):
        return 0.0


def sp_factor(era: float | None, ip: float | None) -> float:
    """Quality multiplier for a pitcher's runs-suppression vs league avg."""
    if era is None or ip is None or ip < MIN_IP_FOR_SIGNAL:
        return 1.0
    weighted = (era * ip + LEAGUE_ERA * IP_PRIOR) / (ip + IP_PRIOR)
    factor = weighted / LEAGUE_ERA
    return max(FACTOR_MIN, min(FACTOR_MAX, factor))


class MLBPitcherScraper:
    """Probable-pitcher + season-stats fetcher with quality factor logic."""

    def __init__(self, season: int = 2026):
        self.season = season
        self.base_url = BASE_URL
        self._stat_cache: dict[int, dict] = {}

    # ---------------- probable pitchers ----------------------------------

    def fetch_probable_pitchers(self, date: str) -> dict[int, dict]:
        """Return {game_pk: {"away": {id,name}, "home": {id,name}}} for `date`.

        Pitchers can be missing (TBD) on doubleheaders or early in the
        morning; missing entries are simply omitted from the inner dicts.
        """
        url = (
            f"{self.base_url}/schedule"
            f"?sportId=1&date={date}"
            f"&hydrate=probablePitcher"
            f"&fields=dates,games,gamePk,teams,away,home,probablePitcher,id,fullName"
        )
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        out: dict[int, dict] = {}
        for date_obj in data.get("dates", []):
            for game in date_obj.get("games", []):
                game_pk = game.get("gamePk")
                if not game_pk:
                    continue
                pitchers = {}
                for side in ("away", "home"):
                    pp = game["teams"][side].get("probablePitcher")
                    if pp and pp.get("id"):
                        pitchers[side] = {
                            "id": pp["id"],
                            "name": pp.get("fullName"),
                        }
                if pitchers:
                    out[game_pk] = pitchers
        return out

    # ---------------- season stats ---------------------------------------

    def fetch_season_stats(self, pitcher_id: int) -> dict | None:
        """Current-season pitching stats for one pitcher (cached)."""
        if pitcher_id in self._stat_cache:
            return self._stat_cache[pitcher_id]

        url = (
            f"{self.base_url}/people/{pitcher_id}/stats"
            f"?stats=season&season={self.season}&group=pitching"
        )
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException:
            self._stat_cache[pitcher_id] = None
            return None

        try:
            splits = payload["stats"][0]["splits"]
        except (KeyError, IndexError):
            self._stat_cache[pitcher_id] = None
            return None

        if not splits:
            self._stat_cache[pitcher_id] = None
            return None

        stat = splits[0].get("stat", {})
        ip = _ip_to_float(stat.get("inningsPitched"))
        try:
            era = float(stat.get("era")) if stat.get("era") not in (None, "-.--") else None
        except (TypeError, ValueError):
            era = None
        try:
            whip = float(stat.get("whip")) if stat.get("whip") not in (None, "-.--") else None
        except (TypeError, ValueError):
            whip = None

        out = {
            "ip": ip,
            "era": era,
            "whip": whip,
            "k": stat.get("strikeOuts"),
            "bb": stat.get("baseOnBalls"),
            "starts": stat.get("gamesStarted"),
        }
        self._stat_cache[pitcher_id] = out
        return out

    # ---------------- combined: per-slate factors ------------------------

    def fetch_factors_for_slate(self, slate: list[dict]) -> dict[int, dict]:
        """Return {game_pk: {"away": {...factor...}, "home": {...factor...}}}.

        Each side's value is `{id, name, era, ip, whip, factor}`. Missing
        sides (TBD pitcher, network failure) get an entry with factor=1.0
        so callers can apply the multiplication unconditionally.
        """
        if not slate:
            return {}

        # Bundle by date so we hit the schedule endpoint once per date.
        dates = sorted({g.get("date") for g in slate if g.get("date")})
        probables: dict[int, dict] = {}
        for date in dates:
            try:
                probables.update(self.fetch_probable_pitchers(date))
            except requests.RequestException:
                pass

        out: dict[int, dict] = {}
        for g in slate:
            game_pk = g.get("game_pk")
            if game_pk is None:
                continue
            sides = probables.get(game_pk, {})
            game_dict: dict[str, dict] = {}
            for side in ("away", "home"):
                pitcher = sides.get(side)
                if not pitcher:
                    game_dict[side] = {
                        "id": None, "name": None, "era": None, "ip": None,
                        "whip": None, "factor": 1.0,
                    }
                    continue
                stats = self.fetch_season_stats(pitcher["id"]) or {}
                game_dict[side] = {
                    "id": pitcher["id"],
                    "name": pitcher["name"],
                    "era": stats.get("era"),
                    "ip": stats.get("ip"),
                    "whip": stats.get("whip"),
                    "factor": sp_factor(stats.get("era"), stats.get("ip")),
                }
            out[game_pk] = game_dict
        return out


if __name__ == "__main__":
    import sys, json
    from datetime import datetime

    date = sys.argv[1] if len(sys.argv) > 1 else datetime.utcnow().strftime("%Y-%m-%d")
    scraper = MLBPitcherScraper(season=int(date[:4]))
    pps = scraper.fetch_probable_pitchers(date)
    print(f"{len(pps)} games with probable SPs on {date}")
    for game_pk, sides in list(pps.items())[:5]:
        away = sides.get("away", {}).get("name", "TBD")
        home = sides.get("home", {}).get("name", "TBD")
        print(f"  {game_pk}: {away} vs {home}")
