"""
MLB Pitcher Scraper
===================
Fetches today's probable starting pitchers from statsapi.mlb.com and
each pitcher's current-season stats, then derives a per-pitcher quality
factor used by the projection model to scale the opposing offense.

Quality factor uses **FIP** (Fielding Independent Pitching) rather than
raw ERA, since FIP normalizes for defensive luck (BABIP variance) and
is more predictive of future performance:

    FIP = (13*HR + 3*(BB+HBP) - 2*K) / IP + cFIP    cFIP ≈ 3.10
    weighted_fip = (fip * ip + LEAGUE_FIP * IP_PRIOR) / (ip + IP_PRIOR)
    factor       = weighted_fip / LEAGUE_FIP        clamped to [0.70, 1.30]

If we can't compute FIP for a pitcher (missing components), we fall back
to ERA. The IP-based shrinkage prior keeps a pitcher with 6 great
innings from being projected as the next Bob Gibson.

Also exposes per-team **bullpen** quality factors fetched from the
team's relief pitching split, used by the projection to weight the
late-innings (5/9 SP + 4/9 BP) of full-game runs.

Usage:
    scraper = MLBPitcherScraper(season=2026)
    sp_map  = scraper.fetch_factors_for_slate(slate)   # game_pk -> SP dicts
    bp_map  = scraper.fetch_bullpen_factors(team_codes)
"""

from __future__ import annotations

import requests

BASE_URL = "https://statsapi.mlb.com/api/v1"

LEAGUE_ERA = 4.20            # rough MLB average ERA
LEAGUE_FIP = 4.20            # FIP is calibrated to ERA scale (cFIP does this)
LEAGUE_WHIP = 1.30
FIP_CONSTANT = 3.10          # additive constant so league-avg FIP ≈ league-avg ERA
IP_PRIOR = 50.0              # ghost innings of league-average performance
IP_PRIOR_BULLPEN = 150.0     # bullpens accumulate IP faster across many arms
MIN_IP_FOR_SIGNAL = 5.0      # below this, factor falls back to 1.0
FACTOR_MIN = 0.70
FACTOR_MAX = 1.30


# Reverse lookup of TEAM_MAP (id -> code) so we can take a team code in
# and ask the API for that team's stats by id.
TEAM_CODE_TO_ID = {
    "LAA": 108, "AZ": 109, "BAL": 110, "BOS": 111, "CHC": 112,
    "CIN": 113, "CLE": 114, "COL": 115, "DET": 116, "HOU": 117,
    "KC": 118,  "LAD": 119, "WSH": 120, "NYM": 121, "ATH": 133,
    "PIT": 134, "SD": 135,  "SEA": 136, "SF": 137,  "STL": 138,
    "TB": 139,  "TEX": 140, "TOR": 141, "MIN": 142, "PHI": 143,
    "ATL": 144, "CWS": 145, "MIA": 146, "NYY": 147, "MIL": 158,
    "ARI": 109, "OAK": 133,
}


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


def compute_fip(
    hr: int | None, bb: int | None, hbp: int | None,
    k: int | None, ip: float | None,
) -> float | None:
    """Standard FIP formula. Returns None if any component is missing."""
    if not all(x is not None for x in (hr, bb, hbp, k)) or ip is None or ip < 1:
        return None
    return (13 * hr + 3 * (bb + hbp) - 2 * k) / ip + FIP_CONSTANT


def quality_factor(
    rate: float | None,
    ip: float | None,
    *,
    league_rate: float = LEAGUE_FIP,
    ip_prior: float = IP_PRIOR,
) -> float:
    """Generic shrinkage-style quality multiplier vs league average.

    `rate` is ERA or FIP (both ERA-scale). Lower = better pitcher = lower
    factor = scales opposing offense down. Output is clamped to a
    [FACTOR_MIN, FACTOR_MAX] band so even extreme samples can't break
    the projection.
    """
    if rate is None or ip is None or ip < MIN_IP_FOR_SIGNAL:
        return 1.0
    weighted = (rate * ip + league_rate * ip_prior) / (ip + ip_prior)
    factor = weighted / league_rate
    return max(FACTOR_MIN, min(FACTOR_MAX, factor))


def sp_factor(era: float | None, ip: float | None, fip: float | None = None) -> float:
    """Starting-pitcher quality multiplier. Prefers FIP, falls back to ERA."""
    if fip is not None:
        return quality_factor(fip, ip)
    return quality_factor(era, ip)


def bullpen_factor(era: float | None, ip: float | None) -> float:
    """Team-bullpen quality multiplier. Higher IP prior since bullpens
    aggregate quickly across many relievers."""
    return quality_factor(era, ip, ip_prior=IP_PRIOR_BULLPEN)


class MLBPitcherScraper:
    """Probable-pitcher + season-stats fetcher with quality factor logic."""

    def __init__(self, season: int = 2026):
        self.season = season
        self.base_url = BASE_URL
        self._stat_cache: dict[int, dict] = {}
        self._bullpen_cache: dict[int, dict] = {}

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

        hr = stat.get("homeRuns")
        bb = stat.get("baseOnBalls")
        hbp = stat.get("hitByPitch")
        k = stat.get("strikeOuts")
        fip = compute_fip(hr, bb, hbp, k, ip)

        out = {
            "ip": ip,
            "era": era,
            "fip": round(fip, 2) if fip is not None else None,
            "whip": whip,
            "k": k,
            "bb": bb,
            "hbp": hbp,
            "hr": hr,
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
                    "fip": stats.get("fip"),
                    "ip": stats.get("ip"),
                    "whip": stats.get("whip"),
                    "factor": sp_factor(
                        stats.get("era"), stats.get("ip"), fip=stats.get("fip"),
                    ),
                }
            out[game_pk] = game_dict
        return out

    # ---------------- bullpen --------------------------------------------

    def fetch_team_bullpen_stats(self, team_id: int) -> dict | None:
        """Fetch a team's relief-pitching split for the season."""
        if team_id in self._bullpen_cache:
            return self._bullpen_cache[team_id]

        # statSplits with sitCodes=rp returns relief-only aggregated stats.
        url = (
            f"{self.base_url}/teams/{team_id}/stats"
            f"?stats=statSplits&sitCodes=rp&group=pitching&season={self.season}"
        )
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException:
            self._bullpen_cache[team_id] = None
            return None

        try:
            splits = payload["stats"][0]["splits"]
        except (KeyError, IndexError):
            self._bullpen_cache[team_id] = None
            return None

        if not splits:
            self._bullpen_cache[team_id] = None
            return None

        stat = splits[0].get("stat", {})
        ip = _ip_to_float(stat.get("inningsPitched"))
        try:
            era = float(stat.get("era")) if stat.get("era") not in (None, "-.--") else None
        except (TypeError, ValueError):
            era = None

        out = {
            "ip": ip,
            "era": era,
            "factor": bullpen_factor(era, ip),
        }
        self._bullpen_cache[team_id] = out
        return out

    def fetch_bullpen_factors(self, team_codes: list[str]) -> dict[str, dict]:
        """Return {team_code: {era, ip, factor}} for each requested team.

        Teams whose bullpen stats can't be fetched fall back to factor=1.0.
        """
        out: dict[str, dict] = {}
        for code in team_codes:
            team_id = TEAM_CODE_TO_ID.get(code)
            if team_id is None:
                out[code] = {"era": None, "ip": None, "factor": 1.0}
                continue
            stats = self.fetch_team_bullpen_stats(team_id)
            if stats is None:
                out[code] = {"era": None, "ip": None, "factor": 1.0}
            else:
                out[code] = stats
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
