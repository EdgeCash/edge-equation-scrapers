"""NCAAF scrapers — Edge Equation v5.0.

Mirrors the NFL scrapers; ESPN's college-football endpoint has the
same response shape. Volume is ~10x NFL (130+ FBS teams, Saturday-heavy
slate) so the scraping interface needs the same week/date filters.
"""

from .ncaaf_game_scraper import NCAAFGameScraper

__all__ = ["NCAAFGameScraper"]
