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

from datetime import datetime, timedelta

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

# Phase 2B: weight on last-3-starts FIP when blending into the SP factor.
# 0.30 = 70% season / 30% recent — captures hot/cold streaks without
# overreacting to a single bad outing.
RECENT_BLEND_WEIGHT = 0.30
RECENT_STARTS_WINDOW = 3


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


def _team_bullpen_ip_in_box(box: dict, team_id: int) -> float:
    """Sum reliever (non-starter) IP for `team_id` in a single boxscore.
    The starter is the first entry of `team.pitchers`; everyone else who
    threw is treated as a reliever."""
    teams = box.get("teams") or {}
    for side_label in ("home", "away"):
        side = teams.get(side_label) or {}
        if (side.get("team") or {}).get("id") != team_id:
            continue
        pitchers = side.get("pitchers") or []
        if not pitchers:
            return 0.0
        starter_id = pitchers[0]
        bp_ip = 0.0
        for pdata in (side.get("players") or {}).values():
            pid = (pdata.get("person") or {}).get("id")
            if pid == starter_id or pid is None:
                continue
            ip_str = ((pdata.get("stats") or {}).get("pitching") or {}).get("inningsPitched")
            if ip_str:
                bp_ip += _ip_to_float(ip_str)
        return bp_ip
    return 0.0


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


def blended_sp_factor(
    season: dict | None,
    recent: dict | None,
    recent_weight: float = RECENT_BLEND_WEIGHT,
) -> float:
    """SP factor blended from season FIP + last-N-starts FIP.

    season:  {"era", "fip", "ip"} from fetch_season_stats
    recent:  {"fip", "ip", "starts"} from fetch_recent_form (or None)

    When recent data is missing or thin, falls back gracefully to
    season-only via sp_factor. The blend uses season IP as the
    shrinkage anchor so a single dominant recent outing can't override
    a long sample.
    """
    if not season:
        return 1.0
    season_fip = season.get("fip")
    season_era = season.get("era")
    season_ip = season.get("ip")

    if not recent or recent.get("fip") is None or recent.get("ip", 0) < MIN_IP_FOR_SIGNAL:
        return sp_factor(season_era, season_ip, fip=season_fip)

    recent_fip = recent["fip"]
    recent_ip = recent["ip"]

    if season_fip is None or season_ip is None or season_ip < MIN_IP_FOR_SIGNAL:
        # Season too thin → recent dominates, with its own IP as the anchor.
        return quality_factor(recent_fip, recent_ip)

    blended_fip = (1 - recent_weight) * season_fip + recent_weight * recent_fip
    return quality_factor(blended_fip, season_ip)


def bullpen_factor(era: float | None, ip: float | None) -> float:
    """Team-bullpen quality multiplier. Higher IP prior since bullpens
    aggregate quickly across many relievers."""
    return quality_factor(era, ip, ip_prior=IP_PRIOR_BULLPEN)


# League-average xwOBA against a typical pitcher. Derived from the
# Statcast leaderboards; matches the league_rate role that LEAGUE_FIP
# plays in quality_factor for ERA-scale rates.
LEAGUE_XWOBA = 0.310

# Weight of the prior-season xwOBA factor when blending into the
# current-season ERA/FIP-based factor. 0.30 is small-but-real: gives
# the noise-stripped Statcast signal a stabilizing role without letting
# last year's data override hot/cold current-season form.
XWOBA_BLEND_WEIGHT = 0.30


def xwoba_factor(xwoba: float | None) -> float:
    """Direct quality factor from xwOBA-against. Lower xwOBA = better
    pitcher = factor < 1.0 = scales opp offense down. Clamped to the
    same [FACTOR_MIN, FACTOR_MAX] band as the ERA/FIP path so a single
    extreme season can't break the projection.

    No IP-based shrinkage here because the source data already requires
    >=100 PA to surface (see SplitsLoader.MIN_XSTATS_PA), which is
    enough exit-velo-driven samples for xwOBA to be stable.
    """
    if xwoba is None or xwoba <= 0:
        return 1.0
    return max(FACTOR_MIN, min(FACTOR_MAX, xwoba / LEAGUE_XWOBA))


def blend_with_xwoba(current_factor: float, prior_xwoba: float | None) -> float:
    """Blend the current-season ERA/FIP-based factor with a prior-season
    xwOBA-derived factor. Acts as a stabilizing prior — early in the
    season when current samples are thin, prior xwOBA pulls the factor
    toward last year's noise-stripped baseline; later in the season the
    current factor (already informed by recent-form blending) dominates
    because it has more samples and more recency.

    When prior xwOBA isn't available, returns the current factor
    unchanged. Output stays clamped to the SP factor band.
    """
    if prior_xwoba is None:
        return current_factor
    prior_factor = xwoba_factor(prior_xwoba)
    blended = (
        (1.0 - XWOBA_BLEND_WEIGHT) * current_factor
        + XWOBA_BLEND_WEIGHT * prior_factor
    )
    return max(FACTOR_MIN, min(FACTOR_MAX, blended))


class MLBPitcherScraper:
    """Probable-pitcher + season-stats fetcher with quality factor logic."""

    def __init__(self, season: int = 2026):
        self.season = season
        self.base_url = BASE_URL
        self._stat_cache: dict[int, dict] = {}
        self._bullpen_cache: dict[int, dict] = {}
        self._recent_cache: dict[int, dict] = {}

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

    # ---------------- recent form (last N starts) ------------------------

    def fetch_recent_form(
        self, pitcher_id: int, n_starts: int = RECENT_STARTS_WINDOW,
    ) -> dict | None:
        """Aggregate FIP / IP / K / BB / HR / HBP across the pitcher's
        last N appearances in the season game log. Returns None on
        network failure or when the pitcher has no game log entries.
        Cached per pitcher per scraper instance.
        """
        if pitcher_id in self._recent_cache:
            return self._recent_cache[pitcher_id]

        url = (
            f"{self.base_url}/people/{pitcher_id}/stats"
            f"?stats=gameLog&season={self.season}&group=pitching"
        )
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException:
            self._recent_cache[pitcher_id] = None
            return None

        try:
            splits = payload["stats"][0]["splits"]
        except (KeyError, IndexError):
            self._recent_cache[pitcher_id] = None
            return None

        if not splits:
            self._recent_cache[pitcher_id] = None
            return None

        # Game logs are date-ordered ascending; the most recent N are the tail.
        recent = splits[-n_starts:]

        total_hr = total_bb = total_hbp = total_k = 0
        total_ip = 0.0
        latest_date: str | None = None
        for s in recent:
            stat = s.get("stat") or {}
            total_hr += int(stat.get("homeRuns") or 0)
            total_bb += int(stat.get("baseOnBalls") or 0)
            total_hbp += int(stat.get("hitByPitch") or 0)
            total_k += int(stat.get("strikeOuts") or 0)
            total_ip += _ip_to_float(stat.get("inningsPitched"))
            if s.get("date"):
                latest_date = s["date"]

        fip = compute_fip(total_hr, total_bb, total_hbp, total_k, total_ip)

        out = {
            "starts": len(recent),
            "ip": total_ip,
            "fip": round(fip, 2) if fip is not None else None,
            "hr": total_hr,
            "bb": total_bb,
            "k": total_k,
            "hbp": total_hbp,
            "latest_date": latest_date,
        }
        self._recent_cache[pitcher_id] = out
        return out

    # ---------------- combined: per-slate factors ------------------------

    def fetch_factors_for_slate(
        self, slate: list[dict], splits_loader=None,
    ) -> dict[int, dict]:
        """Return {game_pk: {"away": {...factor...}, "home": {...factor...}}}.

        Each side's value is `{id, name, era, ip, whip, factor}`. Missing
        sides (TBD pitcher, network failure) get an entry with factor=1.0
        so callers can apply the multiplication unconditionally.

        When `splits_loader` is supplied, prior-season Statcast xwOBA-
        against is blended into the SP factor as a stabilizing prior.
        See blend_with_xwoba() for the math. The xwoba and the standalone
        xwoba_factor are also surfaced on the returned dict so callers
        can audit which signal moved the factor.
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
                        "season_factor": 1.0, "prior_xwoba": None,
                        "prior_xwoba_factor": 1.0,
                    }
                    continue
                season_stats = self.fetch_season_stats(pitcher["id"]) or {}
                recent_stats = self.fetch_recent_form(pitcher["id"])
                season_factor = blended_sp_factor(season_stats, recent_stats)

                prior_xwoba = None
                prior_xw_factor = 1.0
                if splits_loader is not None:
                    prior_xwoba = splits_loader.pitcher_xwoba(
                        pitcher["id"], self.season,
                    )
                    if prior_xwoba is not None:
                        prior_xw_factor = xwoba_factor(prior_xwoba)
                combined = blend_with_xwoba(season_factor, prior_xwoba)

                game_dict[side] = {
                    "id": pitcher["id"],
                    "name": pitcher["name"],
                    "era": season_stats.get("era"),
                    "fip": season_stats.get("fip"),
                    "ip": season_stats.get("ip"),
                    "whip": season_stats.get("whip"),
                    "recent_fip": (recent_stats or {}).get("fip"),
                    "recent_ip": (recent_stats or {}).get("ip"),
                    "recent_starts": (recent_stats or {}).get("starts"),
                    # Three flavors of the SP factor surfaced separately
                    # so the workflow log + downstream auditing can see
                    # which signal moved which.
                    "season_factor": season_factor,
                    "prior_xwoba": prior_xwoba,
                    "prior_xwoba_factor": prior_xw_factor,
                    "factor": combined,
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

    def fetch_bullpen_factors(
        self,
        team_codes: list[str],
        target_date: str | None = None,
        include_workload: bool = True,
        lookback_days: int = 3,
    ) -> dict[str, dict]:
        """Return {team_code: {era, ip, factor, ...}} for each requested team.

        Teams whose bullpen stats can't be fetched fall back to factor=1.0.

        When `include_workload` is true and `target_date` is supplied, the
        returned factor is the SEASON-quality factor multiplied by a
        recent-workload fatigue multiplier. The raw season factor and the
        workload data are also returned in the dict so callers can inspect
        which signal contributed.
        """
        out: dict[str, dict] = {}
        for code in team_codes:
            team_id = TEAM_CODE_TO_ID.get(code)
            if team_id is None:
                out[code] = {
                    "era": None, "ip": None, "factor": 1.0,
                    "season_factor": 1.0, "fatigue_factor": 1.0,
                }
                continue
            stats = self.fetch_team_bullpen_stats(team_id)
            if stats is None:
                out[code] = {
                    "era": None, "ip": None, "factor": 1.0,
                    "season_factor": 1.0, "fatigue_factor": 1.0,
                }
            else:
                out[code] = {
                    **stats,
                    "season_factor": stats["factor"],
                    "fatigue_factor": 1.0,
                }

        if include_workload and target_date:
            workload = self.fetch_recent_bullpen_workload(
                team_codes, target_date=target_date, lookback_days=lookback_days,
            )
            for code in team_codes:
                w = workload.get(code) or {}
                fatigue = w.get("fatigue_factor", 1.0)
                # Combine season-quality factor with fatigue. Higher fatigue
                # = pen more tired = opp offense allowed to score more = the
                # bp_factor (which scales DOWN opp runs when good) shifts UP
                # toward 1.0 / above 1.0.
                combined = out[code].get("season_factor", 1.0) * fatigue
                # Clamp to [FACTOR_MIN, FACTOR_MAX] using the same band the
                # quality_factor helper uses, so a tired-but-elite pen stays
                # bounded.
                combined = max(FACTOR_MIN, min(FACTOR_MAX, combined))
                out[code]["fatigue_factor"] = fatigue
                out[code]["bp_ip_recent"] = w.get("bp_ip_recent")
                out[code]["n_games_recent"] = w.get("n_games_recent")
                out[code]["factor"] = combined
        return out

    # ---------------- recent workload ------------------------------------

    def fetch_recent_bullpen_workload(
        self,
        team_codes: list[str],
        target_date: str,
        lookback_days: int = 3,
    ) -> dict[str, dict]:
        """For each team, sum reliever IP across the lookback_days games
        BEFORE `target_date`. Returns {team_code: {bp_ip_recent: float,
        n_games_recent: int, fatigue_factor: float}}.

        Fatigue factor formula: each IP above the "normal" 3 IP/game of
        bullpen workload bumps the multiplier by 1.5%, capped at 1.15
        (a tired pen gives up at most 15% more runs in our model). Below
        normal (well-rested), factor = 1.0.

        On any API failure for a team, that team falls back to a neutral
        1.0 factor — never blocks the daily build.
        """
        empty = {"bp_ip_recent": 0.0, "n_games_recent": 0, "fatigue_factor": 1.0}
        try:
            target_dt = datetime.fromisoformat(target_date)
        except (TypeError, ValueError):
            return {code: empty for code in team_codes}

        end_date = (target_dt - timedelta(days=1)).strftime("%Y-%m-%d")
        start_date = (target_dt - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

        # Build a quick reverse lookup for team_id → team_code so we can
        # pluck the right side out of each boxscore.
        id_to_code = {tid: code for code, tid in TEAM_CODE_TO_ID.items()}
        wanted_team_ids = {
            TEAM_CODE_TO_ID[code] for code in team_codes
            if code in TEAM_CODE_TO_ID
        }

        sched_url = (
            f"{self.base_url}/schedule"
            f"?sportId=1&startDate={start_date}&endDate={end_date}"
        )
        try:
            resp = requests.get(sched_url, timeout=30)
            resp.raise_for_status()
            sched = resp.json()
        except requests.RequestException:
            return {code: dict(empty) for code in team_codes}

        # team_id → list of game_pks the team played in the window
        team_games: dict[int, list[int]] = {tid: [] for tid in wanted_team_ids}
        for date_block in sched.get("dates", []) or []:
            for g in date_block.get("games", []) or []:
                if (g.get("status") or {}).get("abstractGameState") != "Final":
                    continue
                game_pk = g.get("gamePk")
                if not game_pk:
                    continue
                home_id = ((g.get("teams") or {}).get("home") or {}).get("team", {}).get("id")
                away_id = ((g.get("teams") or {}).get("away") or {}).get("team", {}).get("id")
                if home_id in team_games:
                    team_games[home_id].append(game_pk)
                if away_id in team_games:
                    team_games[away_id].append(game_pk)

        # Boxscore cache so a single game (which has both teams) is only
        # fetched once even though both teams want it.
        box_cache: dict[int, dict] = {}

        out: dict[str, dict] = {}
        for code in team_codes:
            team_id = TEAM_CODE_TO_ID.get(code)
            if team_id is None:
                out[code] = dict(empty)
                continue
            game_pks = team_games.get(team_id, [])
            bp_ip_total = 0.0
            for pk in game_pks:
                box = box_cache.get(pk)
                if box is None:
                    try:
                        bresp = requests.get(
                            f"{self.base_url}/game/{pk}/boxscore", timeout=30,
                        )
                        bresp.raise_for_status()
                        box = bresp.json()
                        box_cache[pk] = box
                    except requests.RequestException:
                        continue
                bp_ip_total += _team_bullpen_ip_in_box(box, team_id)

            n_games = len(game_pks)
            normal_bp_ip = 3.0 * n_games  # ~3 IP/game is typical bullpen share
            extra_ip = max(0.0, bp_ip_total - normal_bp_ip)
            # 1.5% per extra IP, capped at 15% total escalation. Empirically
            # tired pens give up 0.1-0.3 extra runs/game; this captures it.
            fatigue_factor = min(1.15, 1.0 + extra_ip * 0.015)
            out[code] = {
                "bp_ip_recent": round(bp_ip_total, 1),
                "n_games_recent": n_games,
                "fatigue_factor": round(fatigue_factor, 4),
            }
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
