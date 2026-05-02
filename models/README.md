# models/

Sport-agnostic and forward-looking model components.

## Current contents

| Module | Status |
|--------|--------|
| `mlb/player_props.py` | 🟣 EXPERIMENTAL — pitcher Ks, batter hits, batter total bases. Sandboxed; outputs only land in `data/experimental/mlb-props/`. See [BRAND_GUIDE Sandbox section](../docs/BRAND_GUIDE.md). |

The MLB **game-level** projection model still lives at `exporters/mlb/projections.py` for historical reasons (it grew up alongside the daily exporter).

## Why it exists today

Setting up the directory now so:

1. NFL / NCAAF projection models have a canonical home when they come online (June–August per BRAND_GUIDE Dev Priorities).
2. Cross-sport probability helpers (NegBin, Skellam, normal CDF) can migrate here when a second sport needs them.
3. Model-versioning utilities (calibration tracking, A/B comparison helpers) can land here without cluttering exporters/.

## Migration plan

When we add a second sport:

1. Move `exporters/mlb/projections.py` → `models/mlb/projection.py` (rename for clarity).
2. Extract pure-math helpers (`poisson_pmf`, `negbin_pmf`, `prob_over_under_smart`, etc.) to `models/distributions.py`.
3. Each sport's projection model imports from `models/distributions.py` and lives at `models/<sport>/projection.py`.
4. `exporters/<sport>/daily_spreadsheet.py` keeps the orchestration + output logic only.

The split makes the pure model logic testable in isolation and makes it obvious where to look when a probability calculation needs to change.

## What does NOT belong here

- Output assembly, spreadsheet writers, JSON formatters → `exporters/`
- Data ingestion, API clients → `scrapers/`
- Sport-specific tables (park factors, team mappings) — stay alongside the sport's other code
- Cross-sport infrastructure (Odds API quota log, request retries) → `global_utils/`
