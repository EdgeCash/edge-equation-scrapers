"""NFL scrapers — Edge Equation v5.0.

Mirrors the MLB scrapers' interface so the same projection-model
patterns (factor stacking, NegBin, calibration, gating) can apply
once we have enough seasons of NFL data to fit on.
"""

from .nfl_game_scraper import NFLGameScraper

__all__ = ["NFLGameScraper"]
