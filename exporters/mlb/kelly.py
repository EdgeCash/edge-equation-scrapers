"""
Kelly criterion sizing helper.
==============================
Translates a model probability + market price into a recommended bet
size. Defaults to half-Kelly with a hard 5% cap, which is the
practical sweet spot for sports markets where edge estimates are
noisy.

Convention used throughout:
    decimal_odds = American odds converted to decimal form
        -110 -> 1.909
        +120 -> 2.20
        -150 -> 1.667
"""

from __future__ import annotations

DEFAULT_DECIMAL_ODDS = 1.909   # -110 standard juice
HALF_KELLY = 0.5
MAX_KELLY_FRACTION = 0.05      # 5% bankroll cap


def american_to_decimal(american: int | float) -> float:
    """Convert American odds (e.g. -110, +145) to decimal form."""
    am = float(american)
    if am > 0:
        return round(1 + am / 100, 4)
    if am < 0:
        return round(1 + 100 / -am, 4)
    return 1.0


def decimal_to_american(decimal: float) -> int:
    """Convert decimal odds back to American (rounded)."""
    if decimal is None or decimal <= 1.0:
        return 0
    if decimal >= 2.0:
        return round((decimal - 1) * 100)
    return round(-100 / (decimal - 1))


def kelly_fraction(prob: float, decimal_odds: float = DEFAULT_DECIMAL_ODDS) -> float:
    """Full Kelly fraction. Negative edge clamps to 0 (no bet)."""
    b = decimal_odds - 1
    if b <= 0 or prob <= 0 or prob >= 1:
        return 0.0
    f = (b * prob - (1 - prob)) / b
    return max(0.0, f)


def _tier(fraction: float) -> str:
    """Categorical sizing tier from a half-Kelly fraction."""
    if fraction <= 0.005:
        return "PASS"
    if fraction <= 0.015:
        return "0.5u"
    if fraction <= 0.030:
        return "1u"
    if fraction <= 0.050:
        return "2u"
    return "3u"


def tier_from_pct(kelly_pct: float | None) -> str:
    """Public tier helper — accepts a half-Kelly percentage (e.g. 2.5)."""
    if kelly_pct is None:
        return "PASS"
    return _tier(max(0.0, kelly_pct) / 100.0)


def kelly_advice(
    prob: float,
    decimal_odds: float = DEFAULT_DECIMAL_ODDS,
    fraction_of_kelly: float = HALF_KELLY,
    cap: float = MAX_KELLY_FRACTION,
) -> dict:
    """
    Compute a Kelly recommendation suitable for spreadsheet display.

    Returns a dict with the model probability, fair odds, raw and sized
    Kelly percentages, and a categorical tier ("PASS" / "0.5u" / ... / "3u").
    """
    full = kelly_fraction(prob, decimal_odds)
    sized = min(full * fraction_of_kelly, cap)
    return {
        "model_prob": round(prob, 3),
        "fair_odds_dec": round(1 / prob, 3) if 0 < prob < 1 else None,
        "decimal_odds_used": decimal_odds,
        "kelly_full_pct": round(full * 100, 2),
        "kelly_pct": round(sized * 100, 2),
        "kelly_advice": _tier(sized),
    }


def edge_pct(prob: float, decimal_odds: float | None) -> float | None:
    """
    Vig-inclusive edge in percentage points: model probability minus the
    market-implied probability (1 / decimal_odds).

    Positive edge = model thinks the pick wins more often than the price
    pays. To turn a profit at scale you want this to be at least a few
    percentage points (typically 3%+) since closing-line variance and
    model-error variance eat thinner edges.

    Returns None if no market price was available.
    """
    if decimal_odds is None or decimal_odds <= 1.0 or not (0 < prob < 1):
        return None
    return round((prob - 1.0 / decimal_odds) * 100, 2)
