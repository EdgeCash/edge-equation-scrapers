"""
Odds-API multi-sport backfill + daily-snapshot scraper.

`fetch_seasons()` walks the date list from a sport's existing
`data/backfill/{sport}/{season}/games.json` and pulls one HISTORICAL
snapshot per game-day. `snapshot_today()` calls the LIVE endpoint and
merges it into the appropriate season's lines file.

Both modes write to the same per-season `lines.json` keyed by
(date, away_team, home_team) — historical snapshots populate the
season backwards; daily live snapshots keep the current season fresh.

Idempotent: re-runs skip game-days already covered (historical) or
overwrite the day's entries with the latest snapshot (live, so closing
lines win out over earlier pregame ones).

Credit cost (May 2026, $30/mo plan):
    historical: 10 credits per call → 1 call per game-day per sport
    live:        1 credit per call → 1 call per day per sport

Used by:
    run_{nhl,nba,wnba}_lines_backfill.py
    run_{nhl,nba,wnba}_lines_daily.py
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable

from scrapers.odds_api.odds_api_harvester import OddsApiHarvester


def _load_games(games_path: Path) -> list[dict]:
    if not games_path.exists():
        return []
    try:
        return json.loads(games_path.read_text())
    except (OSError, json.JSONDecodeError):
        return []


def _line_key(entry: dict) -> tuple[str, str, str]:
    """Identifies a single game across snapshots. Date + teams is more
    robust than The Odds API's event_id (which can change over re-pulls
    of historical snapshots)."""
    commence = (entry.get("commence_time") or "")[:10]
    return (
        commence,
        entry.get("away_team") or "",
        entry.get("home_team") or "",
    )


class OddsApiBackfillScraper:
    """Per-season historical lines harvester for any Odds-API-supported
    sport. Sport identity is supplied by the caller via `sport_key` and
    `team_name_to_code`."""

    def __init__(
        self,
        sport_key: str,
        team_name_to_code: dict[str, str],
        output_root: Path,
        api_key: str,
        quota_log_path: Path | None = None,
        request_interval_s: float = 0.5,
    ):
        self.sport_key = sport_key
        self.team_name_to_code = team_name_to_code
        self.output_root = Path(output_root)
        self.harvester = OddsApiHarvester(
            api_key=api_key,
            quota_log_path=quota_log_path,
            request_interval_s=request_interval_s,
        )

    def fetch_seasons(
        self,
        seasons: Iterable[int],
        snapshot_hour_utc: int = 22,
        verbose: bool = True,
    ) -> dict[int, dict]:
        report: dict[int, dict] = {}
        for season in seasons:
            if verbose:
                print(f"\n=== {self.sport_key} Lines — season {season} ===")
            report[season] = self.fetch_season(
                season,
                snapshot_hour_utc=snapshot_hour_utc,
                verbose=verbose,
            )
        return report

    def fetch_season(
        self,
        season: int,
        snapshot_hour_utc: int = 22,
        verbose: bool = True,
    ) -> dict:
        """Fetch historical snapshots for every unique game-day in
        the season. Persists merged result to lines.json. Idempotent:
        skips dates we already have lines for."""
        games_path = self.output_root / str(season) / "games.json"
        lines_path = self.output_root / str(season) / "lines.json"

        games = _load_games(games_path)
        if not games:
            msg = f"games.json empty/missing at {games_path}"
            if verbose:
                print(f"  {msg}")
            return {"error": msg, "snapshots_fetched": 0, "games_with_lines": 0}

        # Existing lines (load + index).
        existing_lines: list[dict] = []
        if lines_path.exists():
            try:
                existing_lines = json.loads(lines_path.read_text())
            except (OSError, json.JSONDecodeError):
                existing_lines = []
        by_key: dict[tuple[str, str, str], dict] = {
            _line_key(e): e for e in existing_lines
        }

        # Unique game-dates with at least one game we don't already have
        # lines for. ESPN dates are YYYY-MM-DD strings.
        all_dates = sorted({g.get("date") for g in games if g.get("date")})
        dates_with_coverage_gap = [
            d for d in all_dates
            if not self._all_games_covered_on(d, games, by_key)
        ]

        if verbose:
            covered = len(all_dates) - len(dates_with_coverage_gap)
            print(
                f"  {len(all_dates)} total game-days; "
                f"{covered} already covered, "
                f"{len(dates_with_coverage_gap)} to fetch."
            )

        snapshots_fetched = 0
        for i, d in enumerate(dates_with_coverage_gap, 1):
            snap_iso = f"{d}T{snapshot_hour_utc:02d}:00:00Z"
            try:
                snap = self.harvester.fetch_historical(
                    self.sport_key,
                    self.team_name_to_code,
                    snap_iso,
                )
            except Exception as e:
                if verbose:
                    print(f"    [{i}/{len(dates_with_coverage_gap)}] {d}: error {type(e).__name__}: {e}")
                continue

            snapshots_fetched += 1
            snapshot_at = snap.get("snapshot_at")
            for g in snap.get("games", []):
                if not g.get("commence_time"):
                    continue
                # Filter: only keep snapshot games whose calendar date
                # matches the requested day (Odds-API's window can spill
                # to neighbour days for late tipoffs).
                if (g["commence_time"] or "")[:10] != d:
                    continue
                entry = dict(g)
                entry["snapshot_at"] = snapshot_at
                by_key[_line_key(entry)] = entry

            if verbose and (i % 20 == 0 or i == len(dates_with_coverage_gap)):
                print(
                    f"    [{i}/{len(dates_with_coverage_gap)}] "
                    f"snapshots={snapshots_fetched}, "
                    f"games_with_lines={len(by_key)}"
                )

        # Persist merged.
        merged = sorted(
            by_key.values(),
            key=lambda e: (e.get("commence_time") or "", e.get("away_team") or ""),
        )
        lines_path.parent.mkdir(parents=True, exist_ok=True)
        lines_path.write_text(json.dumps(merged, indent=2, default=str))

        n_with_book = sum(1 for e in merged if e.get("lines"))
        avg_books = (
            sum(len(e.get("lines") or []) for e in merged) / n_with_book
            if n_with_book else 0.0
        )
        if verbose:
            rel = lines_path.relative_to(self.output_root.parent)
            print(
                f"  Wrote {rel}: {len(merged)} games, "
                f"{n_with_book} have ≥1 book, "
                f"avg {avg_books:.1f} books/game"
            )

        return {
            "snapshots_fetched": snapshots_fetched,
            "games_with_lines": len(merged),
            "games_with_book": n_with_book,
            "avg_books": round(avg_books, 1),
        }

    # ---------------- daily live snapshot --------------------------------

    def snapshot_today(
        self,
        season_for_date: Callable[[date], int],
        verbose: bool = True,
    ) -> dict:
        """Pull a single live odds snapshot and merge each game into
        the appropriate season's lines.json. Each game routes to a
        season via the caller-supplied `season_for_date(d)` (NHL/NBA
        seasons span Oct-Jun; WNBA is calendar-year — distinct routing
        rules per sport).

        Re-running during the day is safe — the same (date, away, home)
        key is overwritten with the latest snapshot, so closing-line
        entries replace pregame ones."""
        try:
            snap = self.harvester.fetch_live(
                self.sport_key, self.team_name_to_code,
            )
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

        fetched_at = snap.get("fetched_at")
        # Group by season so we batch one read+write per file rather
        # than re-loading on every game.
        by_season: dict[int, list[dict]] = {}
        for g in snap.get("games", []):
            commence = g.get("commence_time") or ""
            if not commence:
                continue
            try:
                commence_date = datetime.fromisoformat(
                    commence.replace("Z", "+00:00"),
                ).astimezone(timezone.utc).date()
            except ValueError:
                continue
            season = season_for_date(commence_date)
            entry = dict(g)
            entry["snapshot_at"] = fetched_at
            by_season.setdefault(season, []).append(entry)

        report = {
            "fetched_at": fetched_at,
            "games_total": sum(len(v) for v in by_season.values()),
            "seasons": {},
        }
        for season, new_entries in by_season.items():
            lines_path = self.output_root / str(season) / "lines.json"
            existing: list[dict] = []
            if lines_path.exists():
                try:
                    existing = json.loads(lines_path.read_text())
                except (OSError, json.JSONDecodeError):
                    existing = []
            by_key: dict[tuple[str, str, str], dict] = {
                _line_key(e): e for e in existing
            }
            replaced = 0
            added = 0
            for entry in new_entries:
                k = _line_key(entry)
                if k in by_key:
                    replaced += 1
                else:
                    added += 1
                by_key[k] = entry

            merged = sorted(
                by_key.values(),
                key=lambda e: (
                    e.get("commence_time") or "",
                    e.get("away_team") or "",
                ),
            )
            lines_path.parent.mkdir(parents=True, exist_ok=True)
            lines_path.write_text(json.dumps(merged, indent=2, default=str))
            report["seasons"][season] = {
                "added": added,
                "updated": replaced,
                "total": len(merged),
            }
            if verbose:
                rel = lines_path.relative_to(self.output_root.parent)
                print(
                    f"  Season {season} -> {rel}: "
                    f"+{added} new, {replaced} updated, {len(merged)} total"
                )
        return report

    # ---------------- internals ------------------------------------------

    @staticmethod
    def _all_games_covered_on(
        date_str: str,
        games: list[dict],
        by_key: dict[tuple[str, str, str], dict],
    ) -> bool:
        """True iff every game on `date_str` already has a line entry
        in `by_key`. Coverage = the (date, away, home) triple matches —
        we don't enforce ≥1 book here because some games legitimately
        have no books (e.g. preseason)."""
        for g in games:
            if g.get("date") != date_str:
                continue
            key = (
                date_str,
                g.get("away_team") or "",
                g.get("home_team") or "",
            )
            if key not in by_key:
                return False
        return True
