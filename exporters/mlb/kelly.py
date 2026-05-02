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
