# docs/

Project documentation. **The single source of truth for tone, product rules, and operational standards is [`BRAND_GUIDE.md`](BRAND_GUIDE.md).** Everything else in the repo defers to it.

## Files

| Doc | Purpose |
|-----|---------|
| [`BRAND_GUIDE.md`](BRAND_GUIDE.md) | Locked at v0.2. Identity, tagline, conviction tiers, market-gating rules, operational SLAs, dev priorities. |

## When to update the brand guide

Update **before** the code that implements a change to:

- Conviction tier thresholds or naming
- Market-gating criteria (sample size, ROI, Brier)
- Operational SLAs (publication time, grading window, CLV cadence)
- Dev priorities or roadmap

If you find yourself wanting to ship a change and it'd contradict the brand guide, the question to ask isn't "can I bypass this?" — it's "should the brand guide change?". Decide that first; the code follows.

## Future docs (planned)

- `MODEL_NOTES.md` — running log of model version changes, expected impact, observed Brier movement
- `SECURITY.md` — guidance on handling the Odds API key and other secrets when contributing
