"""
MLB Splits + Handedness + Statcast xStats Loader. EXPERIMENTAL.
================================================================
Reads per-season splits.json, the people.json handedness lookup, and
the Statcast statcast_xstats.json expected-stats leaderboards into a
single object that the props backtest can query for handedness-aware
projection rates.

No-look-ahead by construction: this loader only ever returns
PRIOR-season data when asked about season N. So projecting a 2024
game uses only 2023 splits and 2023 xStats — both genuinely available
in real time the morning of every 2024 game.

For the earliest backfilled season (where prior is missing), every
lookup returns None and the caller falls back to the running-aggregate
rate it would've used pre-feature.

Sample threshold:
  - Splits: ignore below 30 PA / batters-faced.
  - Statcast xStats: ignore below 100 PA (to keep noise out of expected
    rates). xStats fall back to actual AVG/SLG from the same season
    above this threshold isn't met, since AVG/SLG aren't expected
    estimates and don't suffer the same small-sample noise.

Decision tree the projector uses for hitter AVG (and analogously SLG):
  1. Prior-season vL/vR AVG (handedness-specific) — most matchup-aware
  2. Prior-season xBA (aggregate, expected) — best aggregate estimator
  3. Running current-season AVG (running aggregate) — what we had pre-features
  4. League average (last-resort fallback inside the projector itself)

Usage:
    loader = SplitsLoader(backfill_dir)
    pitch_hand = loader.pitch_hand(player_id)            # 'L' | 'R' | None
    bat_side = loader.effective_bat_side(player_id, opp_pitch_hand)
    avg = loader.hitter_avg_vs(player_id, season, opp_pitch_hand)
    slg = loader.hitter_slg_vs(player_id, season, opp_pitch_hand)
    xba = loader.hitter_xba(player_id, season)
    xslg = loader.hitter_xslg(player_id, season)
    baa = loader.pitcher_baa_vs(player_id, season, opp_bat_side)
    k_per_pa = loader.pitcher_k_per_pa_vs(player_id, season, opp_bat_side)

All numeric methods return float | None — None if the prior season
has no usable sample for that player.
"""

from __future__ import annotations

import json
from pathlib import Path

# Below this many PAs / batters-faced, the split is too noisy to trust.
MIN_HANDEDNESS_PA = 30
MIN_HANDEDNESS_BF = 30

# Statcast xStats need a larger sample to be stable — exit-velocity
# distributions are heavy-tailed.
MIN_XSTATS_PA = 100


class SplitsLoader:
    def __init__(self, backfill_dir: Path | str):
        self.backfill_dir = Path(backfill_dir)
        # Lazy-load: caches built on first access per season.
        self._splits_by_season: dict[int, dict | None] = {}
        self._xstats_by_season: dict[int, dict | None] = {}
        self._people: dict | None = None

    # ---------------- people / handedness -----------------------------

    def _load_people(self) -> dict:
        if self._people is None:
            path = self.backfill_dir / "people.json"
            if path.exists():
                try:
                    self._people = json.loads(path.read_text())
                except (OSError, json.JSONDecodeError):
                    self._people = {"players": {}}
            else:
                self._people = {"players": {}}
        return self._people

    def pitch_hand(self, player_id: int) -> str | None:
        """'L' | 'R' | None for the pitcher's throwing hand."""
        person = self._load_people().get("players", {}).get(str(player_id))
        if not person:
            return None
        return person.get("pitch_hand")

    def bat_side(self, player_id: int) -> str | None:
        """'L' | 'R' | 'S' (switch) | None for the batter's stance."""
        person = self._load_people().get("players", {}).get(str(player_id))
        if not person:
            return None
        return person.get("bat_side")

    def effective_bat_side(
        self, player_id: int, opp_pitch_hand: str | None,
    ) -> str | None:
        """Switch hitters bat L vs RHP, R vs LHP. For one-handed batters
        we just return their stance. None if either input is unknown."""
        side = self.bat_side(player_id)
        if side is None:
            return None
        if side == "S":
            if opp_pitch_hand not in ("L", "R"):
                return None
            return "L" if opp_pitch_hand == "R" else "R"
        return side  # 'L' or 'R'

    # ---------------- per-season splits -------------------------------

    def _load_season(self, season: int) -> dict | None:
        if season not in self._splits_by_season:
            path = self.backfill_dir / str(season) / "splits.json"
            if path.exists():
                try:
                    self._splits_by_season[season] = json.loads(path.read_text())
                except (OSError, json.JSONDecodeError):
                    self._splits_by_season[season] = None
            else:
                self._splits_by_season[season] = None
        return self._splits_by_season[season]

    def _prior_player_split(
        self, player_id: int, season: int, group: str, side_key: str,
    ) -> dict | None:
        """Return the prior-season {stat: value, ...} dict for this player
        on this side, or None if unavailable. side_key in {'vl', 'vr'}."""
        prior = self._load_season(season - 1)
        if prior is None:
            return None
        player = prior.get(group, {}).get(str(player_id))
        if not player:
            return None
        return player.get(side_key)

    # ---------------- per-season Statcast xStats ----------------------

    def _load_season_xstats(self, season: int) -> dict | None:
        if season not in self._xstats_by_season:
            path = self.backfill_dir / str(season) / "statcast_xstats.json"
            if path.exists():
                try:
                    self._xstats_by_season[season] = json.loads(path.read_text())
                except (OSError, json.JSONDecodeError):
                    self._xstats_by_season[season] = None
            else:
                self._xstats_by_season[season] = None
        return self._xstats_by_season[season]

    def _prior_xstats_player(
        self, player_id: int, season: int, group: str,
    ) -> dict | None:
        """Prior-season Statcast xStats row for the player, or None."""
        prior = self._load_season_xstats(season - 1)
        if prior is None:
            return None
        return prior.get(group, {}).get(str(player_id))

    def hitter_xba(self, player_id: int, season: int) -> float | None:
        """Prior-season Statcast expected BA. None if sample below threshold
        or unavailable. Cleaner than running AVG: filters out luck-driven
        BABIP variance."""
        row = self._prior_xstats_player(player_id, season, "batting")
        if not row:
            return None
        if self._to_int(row.get("pa")) < MIN_XSTATS_PA:
            return None
        return row.get("xba")

    def hitter_xslg(self, player_id: int, season: int) -> float | None:
        """Prior-season Statcast expected SLG."""
        row = self._prior_xstats_player(player_id, season, "batting")
        if not row:
            return None
        if self._to_int(row.get("pa")) < MIN_XSTATS_PA:
            return None
        return row.get("xslg")

    def pitcher_xba(self, player_id: int, season: int) -> float | None:
        """Prior-season Statcast expected BA against this pitcher."""
        row = self._prior_xstats_player(player_id, season, "pitching")
        if not row:
            return None
        if self._to_int(row.get("pa")) < MIN_XSTATS_PA:
            return None
        return row.get("xba")

    def pitcher_xwoba(self, player_id: int, season: int) -> float | None:
        """Prior-season Statcast expected wOBA against this pitcher.
        wOBA captures contact quality across all PA outcomes (HR, BB,
        singles, etc.) weighted by run value, which is a better
        single-number proxy for run-suppression talent than ERA or FIP."""
        row = self._prior_xstats_player(player_id, season, "pitching")
        if not row:
            return None
        if self._to_int(row.get("pa")) < MIN_XSTATS_PA:
            return None
        return row.get("xwoba")

    @staticmethod
    def _to_int(v) -> int:
        if v is None or v == "":
            return 0
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _to_float_pct(v) -> float | None:
        """MLB API returns rates as strings like '.311'. Convert to 0.311."""
        if v is None or v == "":
            return None
        try:
            return float(str(v))
        except (TypeError, ValueError):
            return None

    # ---------------- hitter rates ------------------------------------

    def hitter_avg_vs(
        self, player_id: int, season: int, opp_pitch_hand: str | None,
    ) -> float | None:
        """Hitter's prior-season AVG when facing pitchers of opp_pitch_hand
        ('L' or 'R'). None if sample below threshold or data missing."""
        if opp_pitch_hand not in ("L", "R"):
            return None
        side_key = "vl" if opp_pitch_hand == "L" else "vr"
        split = self._prior_player_split(player_id, season, "hitting", side_key)
        if not split:
            return None
        ab = self._to_int(split.get("atBats"))
        if ab < MIN_HANDEDNESS_PA:
            return None
        hits = self._to_int(split.get("hits"))
        return hits / ab if ab else None

    def hitter_slg_vs(
        self, player_id: int, season: int, opp_pitch_hand: str | None,
    ) -> float | None:
        """Hitter's prior-season SLG when facing opp_pitch_hand."""
        if opp_pitch_hand not in ("L", "R"):
            return None
        side_key = "vl" if opp_pitch_hand == "L" else "vr"
        split = self._prior_player_split(player_id, season, "hitting", side_key)
        if not split:
            return None
        ab = self._to_int(split.get("atBats"))
        if ab < MIN_HANDEDNESS_PA:
            return None
        tb = self._to_int(split.get("totalBases"))
        return tb / ab if ab else None

    def hitter_pa_vs(
        self, player_id: int, season: int, opp_pitch_hand: str | None,
    ) -> int:
        """Sample size for the relevant split. Useful for caller-side
        decisions (e.g. how confident to be in the projection)."""
        if opp_pitch_hand not in ("L", "R"):
            return 0
        side_key = "vl" if opp_pitch_hand == "L" else "vr"
        split = self._prior_player_split(player_id, season, "hitting", side_key)
        if not split:
            return 0
        return self._to_int(split.get("atBats"))

    # ---------------- pitcher rates -----------------------------------

    def pitcher_baa_vs(
        self, player_id: int, season: int, opp_bat_side: str | None,
    ) -> float | None:
        """Pitcher's prior-season BAA against opp_bat_side ('L' or 'R').
        opp_bat_side should already have switch-hitter flip applied."""
        if opp_bat_side not in ("L", "R"):
            return None
        side_key = "vl" if opp_bat_side == "L" else "vr"
        split = self._prior_player_split(player_id, season, "pitching", side_key)
        if not split:
            return None
        ab = self._to_int(split.get("atBats"))
        if ab < MIN_HANDEDNESS_BF:
            return None
        hits = self._to_int(split.get("hits"))
        return hits / ab if ab else None

    def pitcher_k_per_pa_vs(
        self, player_id: int, season: int, opp_bat_side: str | None,
    ) -> float | None:
        """Pitcher's prior-season K rate per batter-faced vs opp_bat_side."""
        if opp_bat_side not in ("L", "R"):
            return None
        side_key = "vl" if opp_bat_side == "L" else "vr"
        split = self._prior_player_split(player_id, season, "pitching", side_key)
        if not split:
            return None
        bf = self._to_int(split.get("battersFaced"))
        if bf < MIN_HANDEDNESS_BF:
            return None
        k = self._to_int(split.get("strikeOuts"))
        return k / bf if bf else None

    def pitcher_bf_vs(
        self, player_id: int, season: int, opp_bat_side: str | None,
    ) -> int:
        if opp_bat_side not in ("L", "R"):
            return 0
        side_key = "vl" if opp_bat_side == "L" else "vr"
        split = self._prior_player_split(player_id, season, "pitching", side_key)
        if not split:
            return 0
        return self._to_int(split.get("battersFaced"))
