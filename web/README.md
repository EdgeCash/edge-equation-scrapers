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

Then visit http://localhost:3000. The site reads
`/data/mlb/mlb_daily.json` from the parent repo's `public/data/mlb/`. For
local dev, copy or symlink that file into `web/public/data/mlb/`:

```bash
mkdir -p public/data/mlb
ln -s ../../../public/data/mlb/mlb_daily.json public/data/mlb/mlb_daily.json
```

## Production deployment

Two paths:

### Path A — Deploy this repo's `web/` to Vercel (recommended)

1. In the Vercel project settings, set **Root Directory** to `web`.
2. **Build Command**: `npm run build` (default Next.js)
3. The site automatically picks up data files from the repo's
   `public/data/mlb/` because Next.js serves anything under `public/` at
   the URL root. The daily GitHub Actions cron commits new data, Vercel
   redeploys, the site updates.

Note: Vercel will look for `public/` inside the root directory by default.
You may need to either:
- Mount `public/data/` at `web/public/data/` with a build step that copies, OR
- Configure rewrites in `next.config.js` to serve from the parent

The cleanest fix is to add a build script that copies `../public/data` into
`web/public/data` before `next build`. Add to `web/package.json` if needed:

```json
"scripts": {
  "build": "node scripts/copy-data.js && next build"
}
```

### Path B — Copy components into your existing site

If you'd rather keep the website on its current Vercel project:

1. Copy `web/app/`, `web/components/`, `web/lib/types.ts`, and the
   relevant chunks of `web/app/globals.css` into your existing Next.js
   tree. Adjust paths to match your project's structure.
2. Copy `web/tailwind.config.ts` color extensions into your existing
   Tailwind config.
3. Make sure `mlb_daily.json` is fetchable at `/data/mlb/mlb_daily.json`.

## Data dependencies

All pages fetch from `/data/mlb/mlb_daily.json` — the structured payload
written by `exporters/mlb/daily_spreadsheet.py`. Schema documented in
`web/lib/types.ts`. Updated daily by the GitHub Actions cron at 11 AM ET
per the BRAND_GUIDE operational standard.

## Brand compliance

This site implements the locked brand rules. Changes that affect tier
names, edge thresholds, or operational standards should update
`docs/BRAND_GUIDE.md` first, then propagate here.
