"""
MLB Weather Scraper
===================
Pulls game-time weather from Open-Meteo (free, no API key) for each
game on today's slate using the home park's coordinates, then derives
a multiplicative weather factor used by the projection model to scale
totals.

Weather factor (multiplicative, 1.0 = neutral conditions):
    delta  = (temp_F - 65) * 0.005          # ~0.5% per degree
    factor = clamp(1.0 + delta, 0.92, 1.10)

Hot days carry the ball further → more runs. Cold games suppress
offense. Indoor stadiums always return factor 1.0 (Tampa, Toronto,
Houston, Arizona, Texas, Milwaukee, Seattle, Miami — most retractables
spend the regular season closed when weather is bad anyway, so we
treat them as climate-controlled).

Wind direction would matter (out to CF helps, in from CF suppresses)
but per-park orientations vary widely and the magnitude is modest
relative to temperature; skipped for v1. Wind speed is still surfaced
in the output for transparency.

Open-Meteo current-weather endpoint:
    https://api.open-meteo.com/v1/forecast
        ?latitude=...&longitude=...
        &current=temperature_2m,wind_speed_10m,wind_direction_10m,precipitation
        &temperature_unit=fahrenheit&wind_speed_unit=mph
"""

from __future__ import annotations

import requests

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


# Ballpark coordinates (lat/lon) and dome flag, keyed by team code.
# Retractable-roof parks marked dome=True (treat as climate controlled).
BALLPARK_COORDS = {
    "AZ":  {"lat": 33.4453, "lon": -112.0667, "venue": "Chase Field",            "dome": True},
    "ARI": {"lat": 33.4453, "lon": -112.0667, "venue": "Chase Field",            "dome": True},
    "ATL": {"lat": 33.8908, "lon":  -84.4678, "venue": "Truist Park",            "dome": False},
    "BAL": {"lat": 39.2839, "lon":  -76.6217, "venue": "Camden Yards",           "dome": False},
    "BOS": {"lat": 42.3467, "lon":  -71.0972, "venue": "Fenway Park",            "dome": False},
    "CHC": {"lat": 41.9484, "lon":  -87.6553, "venue": "Wrigley Field",          "dome": False},
    "CWS": {"lat": 41.8300, "lon":  -87.6339, "venue": "Rate Field",             "dome": False},
    "CIN": {"lat": 39.0975, "lon":  -84.5067, "venue": "Great American Ballpark","dome": False},
    "CLE": {"lat": 41.4962, "lon":  -81.6852, "venue": "Progressive Field",      "dome": False},
    "COL": {"lat": 39.7559, "lon": -104.9942, "venue": "Coors Field",            "dome": False},
    "DET": {"lat": 42.3390, "lon":  -83.0485, "venue": "Comerica Park",          "dome": False},
    "HOU": {"lat": 29.7572, "lon":  -95.3554, "venue": "Daikin Park",            "dome": True},
    "KC":  {"lat": 39.0517, "lon":  -94.4803, "venue": "Kauffman Stadium",       "dome": False},
    "LAA": {"lat": 33.8003, "lon": -117.8827, "venue": "Angel Stadium",          "dome": False},
    "LAD": {"lat": 34.0739, "lon": -118.2400, "venue": "Dodger Stadium",         "dome": False},
    "MIA": {"lat": 25.7781, "lon":  -80.2197, "venue": "loanDepot park",         "dome": True},
    "MIL": {"lat": 43.0280, "lon":  -87.9711, "venue": "American Family Field",  "dome": True},
    "MIN": {"lat": 44.9817, "lon":  -93.2776, "venue": "Target Field",           "dome": False},
    "NYM": {"lat": 40.7571, "lon":  -73.8458, "venue": "Citi Field",             "dome": False},
    "NYY": {"lat": 40.8296, "lon":  -73.9262, "venue": "Yankee Stadium",         "dome": False},
    "OAK": {"lat": 38.5800, "lon": -121.5125, "venue": "Sutter Health Park",     "dome": False},
    "ATH": {"lat": 38.5800, "lon": -121.5125, "venue": "Sutter Health Park",     "dome": False},
    "PHI": {"lat": 39.9061, "lon":  -75.1665, "venue": "Citizens Bank Park",     "dome": False},
    "PIT": {"lat": 40.4469, "lon":  -80.0058, "venue": "PNC Park",               "dome": False},
    "SD":  {"lat": 32.7073, "lon": -117.1567, "venue": "Petco Park",             "dome": False},
    "SF":  {"lat": 37.7786, "lon": -122.3893, "venue": "Oracle Park",            "dome": False},
    "SEA": {"lat": 47.5914, "lon": -122.3325, "venue": "T-Mobile Park",          "dome": True},
    "STL": {"lat": 38.6226, "lon":  -90.1928, "venue": "Busch Stadium",          "dome": False},
    "TB":  {"lat": 27.7682, "lon":  -82.6534, "venue": "Tropicana Field",        "dome": True},
    "TEX": {"lat": 32.7474, "lon":  -97.0833, "venue": "Globe Life Field",       "dome": True},
    "TOR": {"lat": 43.6414, "lon":  -79.3894, "venue": "Rogers Centre",          "dome": True},
    "WSH": {"lat": 38.8729, "lon":  -77.0074, "venue": "Nationals Park",         "dome": False},
}

NEUTRAL_TEMP_F = 65.0
TEMP_PER_DEGREE = 0.005       # 0.5% runs adjustment per degree above/below
FACTOR_MIN = 0.92
FACTOR_MAX = 1.10


def weather_factor(temp_f: float | None, dome: bool) -> float:
    """Multiplicative weather factor for total-runs projection."""
    if dome:
        return 1.0
    if temp_f is None:
        return 1.0
    delta = (temp_f - NEUTRAL_TEMP_F) * TEMP_PER_DEGREE
    return max(FACTOR_MIN, min(FACTOR_MAX, 1.0 + delta))


class MLBWeatherScraper:
    """Per-game weather pulls + factor derivation."""

    def __init__(self):
        self._cache: dict[tuple[float, float], dict] = {}

    def fetch_for_park(self, lat: float, lon: float) -> dict | None:
        """Pull current weather for a (lat, lon). Cached per coordinate."""
        key = (round(lat, 4), round(lon, 4))
        if key in self._cache:
            return self._cache[key]

        params = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,wind_speed_10m,wind_direction_10m,precipitation",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
        }
        try:
            resp = requests.get(OPEN_METEO_URL, params=params, timeout=20)
            resp.raise_for_status()
            current = resp.json().get("current", {})
        except requests.RequestException:
            self._cache[key] = None
            return None

        out = {
            "temp_f": current.get("temperature_2m"),
            "wind_mph": current.get("wind_speed_10m"),
            "wind_dir": current.get("wind_direction_10m"),
            "precipitation": current.get("precipitation"),
        }
        self._cache[key] = out
        return out

    def fetch_for_slate(self, slate: list[dict]) -> dict[int, dict]:
        """Return {game_pk: {venue, dome, temp_f, wind_mph, ..., factor}}.

        Each game's home team determines the venue. Domes get factor 1.0
        without hitting the weather API.
        """
        out: dict[int, dict] = {}
        for g in slate:
            game_pk = g.get("game_pk")
            if game_pk is None:
                continue
            home = g.get("home_team")
            park = BALLPARK_COORDS.get(home)
            if park is None:
                out[game_pk] = {
                    "venue": None, "dome": False,
                    "temp_f": None, "wind_mph": None, "wind_dir": None,
                    "precipitation": None, "factor": 1.0,
                }
                continue

            if park["dome"]:
                out[game_pk] = {
                    "venue": park["venue"], "dome": True,
                    "temp_f": None, "wind_mph": None, "wind_dir": None,
                    "precipitation": None, "factor": 1.0,
                }
                continue

            wx = self.fetch_for_park(park["lat"], park["lon"]) or {}
            out[game_pk] = {
                "venue": park["venue"],
                "dome": False,
                "temp_f": wx.get("temp_f"),
                "wind_mph": wx.get("wind_mph"),
                "wind_dir": wx.get("wind_dir"),
                "precipitation": wx.get("precipitation"),
                "factor": weather_factor(wx.get("temp_f"), park["dome"]),
            }
        return out


if __name__ == "__main__":
    import sys, json
    scraper = MLBWeatherScraper()
    fake_slate = [{"game_pk": 1, "home_team": sys.argv[1] if len(sys.argv) > 1 else "COL"}]
    out = scraper.fetch_for_slate(fake_slate)
    print(json.dumps(out, indent=2))
