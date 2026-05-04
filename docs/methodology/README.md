# Edge Equation Methodology

Plain-English documentation of the formulas behind every number we publish. Each doc explains the math, lists the constants in production, points to the file/function that implements it, and links to the BRAND_GUIDE rule it serves.

> **Why these docs exist:** *"Radical transparency"* is listed as a Core Value in [BRAND_GUIDE.md](../BRAND_GUIDE.md). Brier scores and ROI are easy to publish; the formulas behind them are easy to bury in code. These pages pull the math out so anyone — auditor, customer, future-us — can verify what's actually being computed.

## Formulas in production

| File | What it documents |
|---|---|
| [`run_projection.md`](./run_projection.md) | How a team's projected runs are computed: season aggregate × recent-form decay × opponent strength × SP factor × BP factor × park × weather × lineup |
| [`sp_factor.md`](./sp_factor.md) | Starting-pitcher quality factor: weighted FIP + last-3-starts blend + prior-season xwOBA prior |
| [`bp_factor.md`](./bp_factor.md) | Bullpen quality factor: season ERA + last-3-day workload fatigue |
| [`gate_logic.md`](./gate_logic.md) | Market gate (≥+1% ROI AND Brier <0.246 over 200+ bets) + per-pick edge thresholds + portfolio cap |
| [`calibration.md`](./calibration.md) | Logistic-slope ML calibration + the validated isotonic alternative |
| [`clv.md`](./clv.md) | Closing-line-value computation + the closing-snapshot pipeline |

## How to read each doc

Every page has the same structure:

1. **What it is** — one paragraph plain-English summary
2. **Why it matters** — what bet-level decision it influences
3. **The formula** — the actual math
4. **Constants in production** — exact numerical values, sourced from the code
5. **Implementation** — file path + key function names
6. **BRAND_GUIDE link** — which rule this serves

## What's NOT in scope

- **Findings / one-off analyses** (e.g. yesterday's ELO finding) live in `data/experimental/` and the corresponding PR descriptions, not here. This directory is for *production formulas*, not exploratory results.
- **Sport-specific scrapers** (NHL parsing, WNBA, etc.) — those are documented inline in their `.py` files since the data shape is the documentation.
- **Sandboxed work** (e.g. player props) — not yet earning publication, not yet in scope here. When a sandboxed market passes the gate and ships, its methodology gets a doc.

## Source-of-truth ordering

If a doc here disagrees with the code, **the code wins** and the doc is a bug. Constants documented here should match the constants imported by the production daily build. Periodic audits + git-grep against `DEFAULT_*` constants will catch drift.

If a doc here disagrees with [BRAND_GUIDE.md](../BRAND_GUIDE.md), **the brand guide wins** and the doc is a bug. The brand guide is the locked product spec.
