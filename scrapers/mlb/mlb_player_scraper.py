"""
MLB Player Props Scraper
========================
Fetches player game logs from the MLB Stats API and grades prop results
(HIT / MISS) for common betting lines:

Pitchers : O4.5 K, O5.5 K, O6.5 K, O7.5 K
Batters  : O0.5 Hits, O1.5 Hits, O1.5 Total Bases, O0.5 HR, O0.5 SB

Data source: https://statsapi.mlb.com (free, no auth required)

Usage:
    python mlb_player_scraper.py                # All tracked players, current season
    python mlb_player_scraper.py --season 2025  # Specific season
"""

import requests
import json
import argparse
from datetime import datetime

BASE_URL = "https://statsapi.mlb.com/api/v1"

TRACKED_PITCHERS = {
    694973: "Paul Skenes",
    669373: "Tarik Skubal",
    554430: "Zack Wheeler",
    519242: "Chris Sale",
    657277: "Logan Webb",
    607192: "Tyler Glasnow",
    808967: "Yoshinobu Yamamoto",
    664285: "Framber Valdez",
    656302: "Dylan Cease",
    543037: "Gerrit Cole",
    669203: "Corbin Burnes",
    675911: "Spencer Strider",
}

TRACKED_BATTERS = {
    660271: "Shohei Ohtani",
    592450: "Aaron Judge",
    665487: "Fernando Tatis Jr.",
    665742: "Juan Soto",
    677951: "Bobby Witt Jr.",
    683002: "Gunnar Henderson",
    605141: "Mookie Betts",
    518692: "Freddie Freeman",
    682829: "Elly De La Cruz",
    660670: "Ronald Acuna Jr.",
    608369: "Corey Seager",
}

TEAM_MAP = {
    108: "LAA", 109: "AZ", 110: "BAL", 111: "BOS", 112: "CHC",
    113: "CIN", 114: "CLE", 115: "COL", 116: "DET", 117: "HOU",
    118: "KC", 119: "LAD", 120: "WSH", 121: "NYM", 133: "ATH",
    134: "PIT", 135: "SD", 136: "SEA", 137: "SF", 138: "STL",
    139: "TB", 140: "TEX", 141: "TOR", 142: "MIN", 143: "PHI",
    144: "ATL", 145: "CWS", 146: "MIA", 147: "NYY", 158: "MIL",
}

PITCHER_LINES = [4.5, 5.5, 6.5, 7.5]
BATTER_HIT_LINES = [0.5, 1.5]
BATTER_TB_LINES = [1.5, 2.5]


class MLBPlayerScraper:
    """Fetch player game logs and grade prop results."""

    def __init__(self, season=2026):
        self.season = season
        self.base_url = BASE_URL

    def fetch_pitcher_log(self, player_id):
        """Fetch pitching game log and grade K props."""
        url = (
            f"{self.base_url}/people/{player_id}/stats"
            f"?stats=gameLog&season={self.season}&group=pitching"
        )
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        splits = resp.json().get("stats", [{}])[0].get("splits", [])

        entries = []
        for i, split in enumerate(splits, 1):
            stat = split.get("stat", {})
            team_id = split.get("team", {}).get("id")
            opp_id = split.get("opponent", {}).get("id")
            ks = stat.get("strikeOuts", 0)

            entry = {
                "game_num": i,
                "date": split.get("date", ""),
                "team": TEAM_MAP.get(team_id, str(team_id)),
                "opponent": TEAM_MAP.get(opp_id, str(opp_id)),
                "ip": stat.get("inningsPitched", "0"),
                "hits": stat.get("hits", 0),
                "runs": stat.get("runs", 0),
                "er": stat.get("earnedRuns", 0),
                "bb": stat.get("baseOnBalls", 0),
                "k": ks,
                "pitches": stat.get("numberOfPitches", 0),
                "decision": stat.get("decision", ""),
            }
            for line in PITCHER_LINES:
                key = f"o{line:.1f}k"
                entry[key] = "HIT" if ks > line else "MISS"
            entries.append(entry)
        return entries

    def fetch_batter_log(self, player_id):
        """Fetch batting game log and grade hit/TB props."""
        url = (
            f"{self.base_url}/people/{player_id}/stats"
            f"?stats=gameLog&season={self.season}&group=hitting"
        )
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        splits = resp.json().get("stats", [{}])[0].get("splits", [])

        entries = []
        for i, split in enumerate(splits, 1):
            stat = split.get("stat", {})
            team_id = split.get("team", {}).get("id")
            opp_id = split.get("opponent", {}).get("id")
            hits = stat.get("hits", 0)
            tb = stat.get("totalBases", 0)
            hr = stat.get("homeRuns", 0)
            sb = stat.get("stolenBases", 0)

            entry = {
                "game_num": i,
                "date": split.get("date", ""),
                "team": TEAM_MAP.get(team_id, str(team_id)),
                "opponent": TEAM_MAP.get(opp_id, str(opp_id)),
                "ab": stat.get("atBats", 0),
                "hits": hits,
                "doubles": stat.get("doubles", 0),
                "triples": stat.get("triples", 0),
                "hr": hr,
                "rbi": stat.get("rbi", 0),
                "bb": stat.get("baseOnBalls", 0),
                "k": stat.get("strikeOuts", 0),
                "sb": sb,
                "tb": tb,
            }
            for line in BATTER_HIT_LINES:
                key = f"o{line:.1f}hits"
                entry[key] = "HIT" if hits > line else "MISS"
            for line in BATTER_TB_LINES:
                key = f"o{line:.1f}tb"
                entry[key] = "HIT" if tb > line else "MISS"
            entry["o0.5hr"] = "HIT" if hr > 0.5 else "MISS"
            entry["o0.5sb"] = "HIT" if sb > 0.5 else "MISS"
            entries.append(entry)
        return entries

    def fetch_all(self):
        """Fetch logs for all tracked pitchers and batters."""
        result = {
            "pitchers": {},
            "batters": {},
            "meta": {
                "season": self.season,
                "fetched_at": datetime.now().isoformat(),
            },
        }
        for pid, name in TRACKED_PITCHERS.items():
            print(f"  Fetching pitcher: {name} ({pid})...")
            try:
                log = self.fetch_pitcher_log(pid)
                result["pitchers"][name] = log
                print(f"    -> {len(log)} starts")
            except Exception as e:
                print(f"    Error: {e}")
                result["pitchers"][name] = []
        for pid, name in TRACKED_BATTERS.items():
            print(f"  Fetching batter: {name} ({pid})...")
            try:
                log = self.fetch_batter_log(pid)
                result["batters"][name] = log
                print(f"    -> {len(log)} games")
            except Exception as e:
                print(f"    Error: {e}")
                result["batters"][name] = []
        return result

    @staticmethod
    def hit_rate(log, prop_key):
        """Calculate HIT percentage for a given prop across a game log."""
        if not log:
            return 0.0
        hits = sum(1 for g in log if g.get(prop_key) == "HIT")
        return round(hits / len(log) * 100, 1)

    def to_json(self, data, path=None):
        output = json.dumps(data, indent=2)
        if path:
            with open(path, "w") as f:
                f.write(output)
        return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MLB Player Props Scraper")
    parser.add_argument("--season", type=int, default=2026)
    args = parser.parse_args()

    scraper = MLBPlayerScraper(season=args.season)
    print(f"MLB Player Props Scraper - {args.season} Season")
    data = scraper.fetch_all()

    print("\nPITCHER SUMMARIES")
    for name, log in data["pitchers"].items():
        if not log:
            print(f"  {name}: No data")
            continue
        rates = [f"O{l}K: {scraper.hit_rate(log, f'o{l:.1f}k')}%" for l in PITCHER_LINES]
        print(f"  {name}: {len(log)} starts | {' | '.join(rates)}")

    print("\nBATTER SUMMARIES")
    for name, log in data["batters"].items():
        if not log:
            print(f"  {name}: No data")
            continue
        print(f"  {name}: {len(log)} games | "
              f"O0.5H: {scraper.hit_rate(log, 'o0.5hits')}% | "
              f"O1.5TB: {scraper.hit_rate(log, 'o1.5tb')}%")
