# scrapers/

Per-sport data ingestion. Each sport gets its own subdirectory with the same shape so projection-model patterns can port across sports cleanly.

## Layout

| Sport | Status | Modules |
|-------|--------|---------|
| [`mlb/`](mlb/README.md) | ✅ Production | game, player, settle, odds, pitcher, weather, lineup |
| [`nfl/`](nfl/README.md) | 🟡 Foundation | game scraper (rest in build queue, June–August) |
| [`ncaaf/`](ncaaf/README.md) | 🟡 Foundation | game scraper (subclasses NFL) |
| `nhl/` | ⚪ Legacy | single-file ESPN scraper from earlier prototypes |
| `soccer/` | ⚪ Legacy | single-file ESPN scraper from earlier prototypes |

## Naming convention

`scrapers/<sport>/<sport>_<thing>_scraper.py` — predictable enough that a new sport can be scaffolded by copying an existing one and renaming.

## Cross-sport helpers

Anything truly sport-agnostic (Odds API quota tracking, generic request retry, etc.) lives in [`global_utils/`](../global_utils/), not here. Sport scrapers import from there. See [`global_utils/quota_log.py`](../global_utils/quota_log.py) for the pattern.

## Adding a new sport

See [`CONTRIBUTING.md`](../CONTRIBUTING.md) for the checklist. Briefly:

1. Create `scrapers/<sport>/` with `__init__.py` and one scraper module per data source (game, odds, etc.).
2. Mirror the MLB scraper interface (`fetch_date`, `fetch_week`, `fetch_season` as appropriate).
3. Output should follow the per-game dict shape used by MLB (`date`, `away_team`, `home_team`, scores, derived bet metrics).
4. Add a folder README spelling out what's done vs. coming.
