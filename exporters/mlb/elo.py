"""
Elo rating system.
==================
Ported from edge-equation-v1 (src/edge_equation/stats/elo.py) and
adapted to v2 conventions. Same stateless, Decimal-based design as
the isotonic port — no data dependencies, deterministic, easy to
audit.

Standard Elo as used in chess and adapted for sports:
    expected_score(R_a, R_b) = 1 / (1 + 10^((R_b - R_a) / 400))
    new_rating = old_rating + K * (actual - expected)

Per-league constants (K_FACTOR + HFA) tuned for sport-specific
volatility. MLB uses a low K (4) because a single game tells you
little about a team's true talent — the season is 162 games and
random variance dominates short windows. NFL uses K=20 because
each of the 17 games carries much more information.

Why Elo for v2 evaluation: our current ProjectionModel uses team
season run rates + recent-form decay + opponent strength. Elo is a
different KIND of signal — a single rating per team that compresses
"how much have they been winning vs expected" across the whole
schedule. Worth A/B-testing whether it adds incremental signal on
top of our existing per-team aggregates, or whether it's just a
compressed restatement of information we already have.

Source: https://github.com/EdgeCash/edge-equation-v1/blob/main/src/edge_equation/stats/elo.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Tuple


# Default starting rating for a team with no history. Standard chess
# convention is 1500; works equally well for sports as long as we're
# consistent.
DEFAULT_RATING = Decimal('1500')

# Per-league tuning. K_FACTOR is the maximum rating swing a single
# game can produce; HFA is the rating bonus the home team gets when
# computing pre-game win probability.
LEAGUE_PARAMS: Dict[str, Dict[str, Decimal]] = {
    "mlb": {"k": Decimal('4'),  "hfa": Decimal('20')},
    "nfl": {"k": Decimal('20'), "hfa": Decimal('55')},
    # NCAAF: shorter season, wider talent gaps, bigger K. HFA lower
    # than NFL because home crowds matter less in college (smaller
    # stadiums for many programs).
    "ncaaf": {"k": Decimal('25'), "hfa": Decimal('40')},
}


@dataclass(frozen=True)
class GameResult:
    """One completed game's bare facts. Used as input to replay()."""
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    # Optional but useful for chronological sorting in replay().
    date: Optional[str] = None


@dataclass(frozen=True)
class EloRatings:
    """Snapshot of every team's rating in a league after replay.

    Frozen because mutation should go through replay() (which produces
    a new EloRatings) — that way callers can't accidentally drift the
    snapshot they're holding while predictions are in flight.
    """
    league: str
    ratings: Dict[str, Decimal] = field(default_factory=dict)
    games: Dict[str, int] = field(default_factory=dict)

    def rating_for(self, team: str) -> Decimal:
        return self.ratings.get(team, DEFAULT_RATING)

    def games_for(self, team: str) -> int:
        return self.games.get(team, 0)

    def to_dict(self) -> dict:
        return {
            "league": self.league,
            "ratings": {t: str(r) for t, r in self.ratings.items()},
            "games": dict(self.games),
        }


class EloCalculator:
    """Stateless Elo math + replay engine."""

    @staticmethod
    def expected_score(rating_a: Decimal, rating_b: Decimal) -> Decimal:
        """Probability that team A beats team B given their current
        ratings. Standard logistic on the rating difference scaled
        by 400."""
        diff = rating_b - rating_a
        # 10^(diff/400) — use float for the exponent to avoid Decimal
        # power-with-non-integer awkwardness, then cast back.
        exp = float(diff) / 400.0
        denom = Decimal('1') + Decimal(str(10.0 ** exp))
        result = Decimal('1') / denom
        return result.quantize(Decimal('0.000001'))

    @staticmethod
    def update(
        rating_home: Decimal,
        rating_away: Decimal,
        home_score: int,
        away_score: int,
        k: Decimal,
        hfa: Decimal,
    ) -> Tuple[Decimal, Decimal]:
        """Apply one game's result. Returns (new_home_rating,
        new_away_rating). HFA is added to the home rating ONLY for
        the expected-score calculation; the published rating doesn't
        carry HFA — it's purely a per-game adjustment."""
        if home_score == away_score:
            actual_home = Decimal('0.5')
        elif home_score > away_score:
            actual_home = Decimal('1')
        else:
            actual_home = Decimal('0')
        actual_away = Decimal('1') - actual_home

        expected_home = EloCalculator.expected_score(
            rating_home + hfa, rating_away,
        )
        expected_away = Decimal('1') - expected_home

        new_home = rating_home + k * (actual_home - expected_home)
        new_away = rating_away + k * (actual_away - expected_away)
        return (
            new_home.quantize(Decimal('0.000001')),
            new_away.quantize(Decimal('0.000001')),
        )

    @staticmethod
    def replay(league: str, results: Iterable[GameResult]) -> EloRatings:
        """Walk results in the supplied order, accumulating ratings.

        Caller is responsible for chronological order — pass results
        sorted by date. We don't sort internally because the caller
        often has richer data (e.g. game time) we'd lose.
        """
        params = LEAGUE_PARAMS.get(league.lower())
        if params is None:
            raise ValueError(f"Unknown league {league!r}; add params to LEAGUE_PARAMS.")
        k = params["k"]
        hfa = params["hfa"]

        ratings: Dict[str, Decimal] = {}
        games: Dict[str, int] = {}

        for r in results:
            home_r = ratings.get(r.home_team, DEFAULT_RATING)
            away_r = ratings.get(r.away_team, DEFAULT_RATING)
            new_home, new_away = EloCalculator.update(
                home_r, away_r, r.home_score, r.away_score, k, hfa,
            )
            ratings[r.home_team] = new_home
            ratings[r.away_team] = new_away
            games[r.home_team] = games.get(r.home_team, 0) + 1
            games[r.away_team] = games.get(r.away_team, 0) + 1

        return EloRatings(league=league.lower(), ratings=ratings, games=games)

    @staticmethod
    def win_probability(
        league: str,
        home_team: str,
        away_team: str,
        ratings: EloRatings,
    ) -> Decimal:
        """Pre-game probability that home_team beats away_team given
        the supplied ratings snapshot. Includes home-field advantage."""
        params = LEAGUE_PARAMS.get(league.lower())
        if params is None:
            raise ValueError(f"Unknown league {league!r}.")
        hfa = params["hfa"]
        home_r = ratings.rating_for(home_team)
        away_r = ratings.rating_for(away_team)
        return EloCalculator.expected_score(home_r + hfa, away_r)
