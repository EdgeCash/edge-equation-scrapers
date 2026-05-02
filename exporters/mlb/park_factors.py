"""
MLB Park Factors
================
Multi-year park factors expressed as a multiplicative adjustment to the
neutral-park run environment (1.00 = league average).

Sources: rolling 3-year averages from Baseball-Reference + FanGraphs.
Updated annually; re-pull from those sources off-season for fresh values.
"""

# Run scoring multiplier per home park, keyed by team code.
PARK_FACTOR = {
    "COL": 1.18,  # Coors Field — thin air, the canonical hitter's park
    "CIN": 1.10,  # Great American Ballpark
    "BOS": 1.08,  # Fenway Park
    "TEX": 1.05,  # Globe Life Field (post-2020 dome era trends back hitter-friendly)
    "TOR": 1.04,  # Rogers Centre
    "NYY": 1.04,  # Yankee Stadium — short porch in right
    "AZ":  1.03,  # Chase Field
    "ARI": 1.03,
    "MIL": 1.02,  # American Family Field
    "PHI": 1.02,  # Citizens Bank Park
    "BAL": 1.02,  # Camden Yards (post-LF wall change)
    "WSH": 1.02,  # Nationals Park
    "CHC": 1.01,  # Wrigley Field
    "ATL": 1.00,  # Truist Park — neutral-ish
    "MIN": 1.00,  # Target Field
    "STL": 1.00,  # Busch Stadium
    "HOU": 0.99,  # Minute Maid (now Daikin Park)
    "CLE": 0.99,  # Progressive Field
    "KC":  0.99,  # Kauffman Stadium
    "CWS": 0.98,  # Rate Field
    "LAA": 0.98,  # Angel Stadium
    "PIT": 0.97,  # PNC Park
    "DET": 0.96,  # Comerica Park
    "LAD": 0.96,  # Dodger Stadium — pitcher-leaning
    "TB":  0.95,  # Tropicana Field
    "ATH": 0.95,  # Sutter Health Park (Sacramento, A's temporary home)
    "SEA": 0.94,  # T-Mobile Park
    "MIA": 0.93,  # loanDepot park — large dimensions
    "NYM": 0.94,  # Citi Field
    "SF":  0.92,  # Oracle Park — marine layer, deep RF
    "SD":  0.92,  # Petco Park — the canonical pitcher's park
}

DEFAULT_PARK_FACTOR = 1.00


def park_factor(home_team: str) -> float:
    """Return the run multiplier for the home team's primary venue."""
    return PARK_FACTOR.get(home_team, DEFAULT_PARK_FACTOR)
