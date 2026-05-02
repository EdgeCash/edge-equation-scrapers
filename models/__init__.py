"""
models — sport-agnostic and forward-looking model components.

Currently a placeholder. The MLB projection model lives at
exporters/mlb/projections.py for historical reasons (it grew out of
the daily exporter). When NFL / NCAAF projection models come online
mid-summer they'll live here as the canonical home, and the MLB model
may migrate too once the per-sport pattern is settled.

What goes here:
- Cross-sport calibration utilities
- Shared probability helpers (NegBin, Skellam, normal CDF)
- Future per-sport projection models (models/nfl/, models/ncaaf/)

What does NOT go here:
- Output assembly, spreadsheet writers, JSON formatters → exporters/
- Data ingestion, API clients → scrapers/
- Sport-specific factors that aren't model code (park factors, team
  mappings) → live alongside the sport's other files
"""
