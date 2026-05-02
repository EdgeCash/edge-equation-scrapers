# Master Brand & Development Outline for Edge Equation

**Version:** 0.2
**Status:** Locked. No pivots without updating this document first.

---

## Identity

**Name:** Edge Equation

**Tagline:** Facts. Not Feelings.

**Mission:** Deliver transparent, high-signal sports analytics through honest modeling, rigorous testing, and public learning.

## Core Values

- **Radical transparency** — Brier, ROI, CLV, model versions are all public
- **Simplicity over complexity**
- **Process > Picks**
- **CLV-first mindset** — closing line value is the gold-standard truth-teller
- **Bet responsibly**

## Conviction Tiers (with Kelly units)

The colored tier indicates how strong the model thinks the edge is. The Kelly unit indicates how much of bankroll to risk. Both ship on every play.

| Tier | Color | Edge | Typical Kelly |
|------|-------|------|---------------|
| Signal Elite | 🔵 Electric Blue | ≥4% | 2u+ |
| Strong Signal | 🟢 Deep Green | 3–4% | 1.5–2u |
| Moderate Signal | 🟡 Amber | 2–3% | 1u |
| Lean Signal | ⚪ Slate | 1–2% | 0.5u (informational only) |
| No Signal | 🔴 Red | <1% | pass |

## Product Rules

- Typically **3–8 high-conviction plays per day**. Some days zero — that's a feature, not a bug.
- **Market gating:** A market is included on the daily card only when its rolling 200+ bet backtest shows **≥+1% ROI AND Brier <0.246**. Re-evaluated weekly. Removing a market from publication is a normal part of the process.
- **Props / NRFI / YRFI / player props:** Gradual rollout, gated on the game-level model proving consistent +CLV first. NRFI/YRFI ships under the existing First Inning market; player-level props (Ks, hits, HRs) wait until the game-level model is profitable for 30+ consecutive days.

## Sandbox protocol

Some markets (currently: MLB player props) are under active development but **not yet earning their way onto the daily card**. We build them out so backtest evidence can accumulate, but everything generated lives outside `public/` — no website surface, no X/social posts, no daily card mention.

**Rules for sandboxed markets:**

- Outputs land in `data/experimental/<market>/` (deliberately NOT under `public/`).
- No web routes consume sandbox data.
- No tier badges, no Kelly units published anywhere user-facing.
- Sandboxed work moves out of the sandbox **only** when it passes the same market gate as live markets: ≥+1% ROI AND Brier <0.246 over 200+ rolling backtest bets.
- Removing a sandboxed market that doesn't earn its way out is a normal, expected outcome. Building doesn't entitle anything to publication.

This protects the brand promise that everything visible has been measured. Building in the open is fine; publishing in the open without evidence is not.

## Operational Standards (the floor for "elite")

1. **Daily card published by 11:00 AM ET** (gives lineups time to set)
2. **CLV snapshot recorded on every published pick** before first pitch
3. **Every resolved pick graded within 24 hours** of game completion
4. **Public 30-day rolling CLV** updated daily, visible to anyone
5. **Fast issue resolution** — pipeline failures surfaced and fixed within 24h
6. Methodology page reflects the live model version

## Development Priorities (Next 8 Weeks)

1. Finalize MLB improvements (Negative Binomial ✅, Run Line inversion ✅, market filters)
2. CLV tracking ✅ (continue refining; surface 30-day rolling on the site)
3. Begin NFL / NCAAF data harvesting (June — July; gets us ahead of peak season)
4. Gradual props expansion (NRFI / YRFI already shipping; player props gated on game-level CLV proof)

---

*Use this document as the single source of truth. Reference sections in commit messages and PR descriptions when work advances a specific area (e.g. "Implements market-gating rule from BRAND_GUIDE Product Rules").*
