# Edge Equation Scrapers

This project consists of various web scrapers for different sports to gather data and provide insights.

## Structure

- `scrapers/` - Contains all scrapers for each sport.
- `exporters/` - Contains files for exporting data formats.
  - `exporters/mlb/` - Daily MLB spreadsheet (Today's Card, 6 game-results bet tabs, Backtest) writing into `public/data/mlb/` for the Vercel site to serve. See `exporters/mlb/README.md`.
- `web/` - Drop-in Next.js components that render the daily MLB spreadsheet on a Vercel-hosted site. See `web/README.md`.
- `.github/workflows/` - Daily automation (GitHub Actions cron that builds the spreadsheet and pushes to `main` for Vercel auto-deploy).
- `global_utils/` - Contains utility functions for handling requests and other common tasks.
- `public/data/` - Static output files served by Vercel.

## Requirements

To install the required packages, use: 

```bash
pip install -r requirements.txt
```

## Usage

To run the scrapers, execute the relevant scripts inside each sport's directory.