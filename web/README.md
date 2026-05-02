# Edge Equation v5.0 — Web

Production website. Fully self-contained Next.js 15 app with TypeScript and
TailwindCSS. Implements the brand and content rules locked in
`docs/BRAND_GUIDE.md`.

## Pages

| Route | Purpose |
|-------|---------|
| `/` | Hero, conviction-tier explainer, core-values pillars, CTA. |
| `/daily-card` | Today's plays with TierBadge + Kelly units. Empty state when the math says pass. |
| `/track-record` | Public backtest ledger: per-market ROI, hit rate, Brier, gate status; daily P&L. |
| `/methodology` | How the model works. The "show your work" page. |

## Visual direction

"Controlled chaos / analytical juxtaposition" — mathematician's chalkboard
in the middle of a loud sportsbook. Dark slate base (`#0a1421`), subtle grid
texture, soft chalk-blue glow accents, electric blue (`#38bdf8`) reserved for
**Signal Elite** tier and primary CTAs.

Hand-drawn imperfections (Caveat font for accents, eraser-smudge SVG
underlines) sit alongside clean Inter body type and crisp data tables —
the chaos and the calm sit together by design.

## Local development

```bash
cd web
npm install
npm run dev
```

Then visit http://localhost:3000. The `dev` script runs `copy-data.js`
first, which mirrors the repo-root `public/data/` into `web/public/data/`
so the site can serve the latest pipeline outputs at `/data/mlb/*`. Run
`npm run copy-data` manually any time you want to refresh after a daily
build commits new files.

## Production deployment (Vercel)

The data files live at the repo root in `public/data/`, generated daily
by the GitHub Actions cron. Next.js only serves files inside its own
project root, so the build script copies them into `web/public/data/` on
every build. Vercel rebuilds on every commit to `main` (including the
cron's daily data commit), so fresh data ships automatically.

### One-time Vercel setup

1. Go to the Vercel dashboard and either create a new project pointing
   at `edgecash/edge-equation-scrapers` or update your existing project.
2. **Settings → Build & Deployment**:
   - **Framework Preset**: Next.js
   - **Root Directory**: `web`
   - **Build Command**: leave default (`npm run build` — already wired
     to copy data first)
   - **Output Directory**: leave default (`.next`)
   - **Install Command**: leave default (`npm install`)
3. **Settings → Git**: ensure the connected branch is `main`.
4. Hit **Deploy**. The site will be live at `<project>.vercel.app`.
5. (Optional) **Settings → Domains**: point your custom domain at the
   project.

### What happens on every push

```
git push                                    # any commit, including the
                                            # daily cron's data update
  → Vercel webhook fires
  → Vercel runs `cd web && npm install`
  → `npm run build` triggers:
      → copy-data.js mirrors ../public/data → web/public/data
      → next build compiles the app
  → Deploy goes live
```

No manual steps after the one-time setup. The 11 AM ET cron commits
new data, Vercel rebuilds within 1-2 minutes, and the site reflects the
fresh card.

## Alternative: copy components into an existing site repo

If you want to keep the website on a separate Vercel project:

1. Copy `web/app/`, `web/components/`, `web/lib/types.ts`, the contents
   of `web/app/globals.css`, and the color extensions from
   `web/tailwind.config.ts` into your existing Next.js tree.
2. Make sure `mlb_daily.json` is fetchable at `/data/mlb/mlb_daily.json`
   in your deployment (you'll need to sync data files between repos).

## Data dependencies

All pages fetch from `/data/mlb/mlb_daily.json` — the structured payload
written by `exporters/mlb/daily_spreadsheet.py`. Schema documented in
`web/lib/types.ts`. Updated daily by the GitHub Actions cron at 11 AM ET
per the BRAND_GUIDE operational standard.

## Brand compliance

This site implements the locked brand rules. Changes that affect tier
names, edge thresholds, or operational standards should update
`docs/BRAND_GUIDE.md` first, then propagate here.
