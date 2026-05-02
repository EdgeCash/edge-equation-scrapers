# MLB Dashboard — Next.js components

Drop-in React components that render the daily MLB spreadsheet on a
Vercel-hosted site. They fetch `public/data/mlb/mlb_daily.json` (which is
generated daily by `exporters/mlb/daily_spreadsheet.py`) and render all 8
tabs with sortable tables and Kelly badges.

## Files

| File | Purpose |
|------|---------|
| `types.ts` | TypeScript interfaces matching `mlb_daily.json`. |
| `components/MLBDashboard.tsx` | Main container: fetches data, manages tab state. Client component. |
| `components/TabTable.tsx` | Generic table renderer for any tab (projections + backfill sections). |
| `components/KellyBadge.tsx` | Color-coded Kelly tier badge (PASS / 0.5u / 1u / 2u / 3u). |
| `app/mlb/page.tsx` | Example App Router page that mounts the dashboard at `/mlb`. |

## Setup

If your Vercel site is **this repo**:

1. Move (or symlink) `web/components/` into your existing `components/` dir, and `web/types.ts` into your project's types directory.
2. Move `web/app/mlb/page.tsx` into your `app/mlb/` directory.
3. Make sure your Next.js config serves `public/data/mlb/` (it does by default — anything under `public/` is a static asset).
4. Visit `https://your-site.vercel.app/mlb`.

If your Vercel site is a **different repo**:

1. Copy the files in `web/` into the matching directories of that repo.
2. The frontend fetches `/data/mlb/mlb_daily.json` — either:
   - Have the daily build in this repo push the JSON into your site repo's `public/data/mlb/`, or
   - Host the JSON elsewhere and pass a full URL via `<MLBDashboard dataUrl="https://..." />`.

## Dependencies

The components use **TailwindCSS** for styling. If your site already has
Tailwind, no extra install is needed. If not, either:

- Add Tailwind (`npm install -D tailwindcss && npx tailwindcss init`), or
- Replace the className strings with your own CSS — every component is a
  thin wrapper, easy to restyle.

No other runtime deps. Uses native `fetch` + React hooks.

## Customization

`<MLBDashboard dataUrl="..." />` — override the JSON URL (defaults to
`/data/mlb/mlb_daily.json`).

The tab order is set in `MLBDashboard.tsx::TAB_ORDER` if you'd rather
default to a different starting tab than Today's Card.
