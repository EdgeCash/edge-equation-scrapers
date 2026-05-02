# global_utils/

Cross-sport helpers — the few things that genuinely belong everywhere.

## What's here

| Module | Purpose |
|--------|---------|
| `quota_log.py` | The Odds API rate-limit header logger. Every sport's odds scraper writes to a per-sport `quota_log.json` file via this helper, so combined burn from MLB + NFL + NCAAF (sharing one API key) is visible at a glance. |

## What goes here

Strictly cross-sport infrastructure:

- ✅ Odds API quota tracking (every sport uses the same API key)
- ✅ Future: shared HTTP retry/backoff logic
- ✅ Future: shared CLV math (it's identical regardless of sport)
- ✅ Future: shared timezone / date helpers if patterns emerge

What does NOT go here:

- ❌ MLB-specific team mappings → `scrapers/mlb/`
- ❌ NFL-specific projection logic → `models/nfl/` (when that lands)
- ❌ Per-sport park factors, lineup data → alongside their sport
- ❌ Web / frontend code → `web/`

## Imports

```python
from global_utils.quota_log import log_quota
log_quota(my_path, response.headers, "baseball_mlb/odds")
```
