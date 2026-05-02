# Edge Equation Scrapers

This project consists of various web scrapers for different sports to gather data and provide insights.

## Structure

- `scrapers/` - Contains all scrapers for each sport.
- `exporters/` - Contains files for exporting data formats.
  - `exporters/mlb/` - Daily MLB spreadsheet (6 tabs of game-results bets) writing into `public/data/mlb/` for the Vercel site to serve. See `exporters/mlb/README.md`.
- `global_utils/` - Contains utility functions for handling requests and other common tasks.
- `public/data/` - Static output files served by Vercel.

## Requirements

To install the required packages, use: 

```bash
pip install -r requirements.txt
```

## Usage

To run the scrapers, execute the relevant scripts inside each sport's directory.