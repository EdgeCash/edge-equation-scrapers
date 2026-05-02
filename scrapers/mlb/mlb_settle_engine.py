"""
MLB Settle Engine
=================
Grades published Edge Equation picks against actual game results.
Designed to run daily to settle yesterday's picks and update the Track Record.

Workflow:
    1. Load yesterday's published picks from the JSON feed
    2. Fetch actual results via MLBGameScraper and MLBPlayerScraper
    3. Grade each pick: WIN / LOSS / PUSH / VOID
    4. Output settled results as JSON for the frontend

Usage:
    python mlb_settle_engine.py                     # Settle yesterday
    python mlb_settle_engine.py --date 2026-05-01   # Settle specific date
    python mlb_settle_engine.py --output settled.json
"""

import json
import argparse
from datetime import datetime, timedelta
from mlb_game_scraper import MLBGameScraper
from mlb_player_scraper import MLBPlayerScraper, TRACKED_PITCHERS, TRACKED_BATTERS


class MLBSettleEngine:
    """Grades picks against actual results."""

    def __init__(self, season=2026):
        self.game_scraper = MLBGameScraper()
        self.player_scraper = MLBPlayerScraper(season=season)

    def grade_moneyline(self, pick, game):
        """Grade a moneyline pick. pick must have 'team'."""
        if game["ml_winner"] == pick["team"]:
            return "WIN"
        return "LOSS"

    def grade_run_line(self, pick, game):
        """Grade a run-line pick. pick must have 'team' and 'spread'."""
        spread = pick.get("spread", 0)
        team = pick["team"]
        if team == game["away_team"]:
            margin = game["away_score"] - game["home_score"]
        else:
            margin = game["home_score"] - game["away_score"]
        adjusted = margin + spread
        if adjusted > 0:
            return "WIN"
        elif adjusted == 0:
            return "PUSH"
        return "LOSS"

    def grade_first5(self, pick, game):
        """Grade a first-5-innings pick. pick must have 'team'."""
        winner = game["f5_winner"]
        if winner == "PUSH":
            return "PUSH"
        if winner == pick["team"]:
            return "WIN"
        return "LOSS"

    def grade_nrfi(self, pick, game):
        """Grade NRFI/YRFI. pick must have 'side' = 'NRFI' or 'YRFI'."""
        if pick["side"] == "NRFI":
            return "WIN" if game["nrfi"] else "LOSS"
        else:
            return "WIN" if not game["nrfi"] else "LOSS"

    def grade_total(self, pick, game):
        """Grade over/under. pick must have 'side' and 'line'."""
        line = pick["line"]
        actual = game["total"]
        if pick["side"] == "OVER":
            if actual > line:
                return "WIN"
            elif actual == line:
                return "PUSH"
            return "LOSS"
        else:
            if actual < line:
                return "WIN"
            elif actual == line:
                return "PUSH"
            return "LOSS"

    def grade_team_total(self, pick, game):
        """Grade team total. pick must have 'team', 'side', 'line'."""
        team = pick["team"]
        if team == game["away_team"]:
            actual = game["away_total"]
        else:
            actual = game["home_total"]
        if pick["side"] == "OVER":
            if actual > pick["line"]:
                return "WIN"
            elif actual == pick["line"]:
                return "PUSH"
            return "LOSS"
        else:
            if actual < pick["line"]:
                return "WIN"
            elif actual == pick["line"]:
                return "PUSH"
            return "LOSS"

    def grade_pitcher_k_prop(self, pick, pitcher_log):
        """Grade a pitcher K prop for a specific game date."""
        for game in pitcher_log:
            if game["date"] == pick["date"]:
                return "WIN" if game["k"] > pick["line"] else "LOSS"
        return "VOID"

    def grade_batter_prop(self, pick, batter_log):
        """Grade a batter prop for a specific game date."""
        stat_key = pick["stat"]
        for game in batter_log:
            if game["date"] == pick["date"]:
                actual = game.get(stat_key, 0)
                return "WIN" if actual > pick["line"] else "LOSS"
        return "VOID"

    def settle_date(self, date, picks):
        """Grade all picks for a given date."""
        games = self.game_scraper.fetch_schedule(date)
        games_by_teams = {}
        for g in games:
            games_by_teams[g["away_team"]] = g
            games_by_teams[g["home_team"]] = g

        player_logs = {}
        player_picks = [p for p in picks if p["bet_type"] in ("pitcher_k", "batter_prop")]
        for pick in player_picks:
            pid = pick.get("player_id")
            if pid and pid not in player_logs:
                if pid in TRACKED_PITCHERS:
                    player_logs[pid] = self.player_scraper.fetch_pitcher_log(pid)
                elif pid in TRACKED_BATTERS:
                    player_logs[pid] = self.player_scraper.fetch_batter_log(pid)

        settled = []
        for pick in picks:
            result = "VOID"
            bt = pick["bet_type"]
            game = games_by_teams.get(pick.get("team"))

            try:
                if bt == "ml" and game:
                    result = self.grade_moneyline(pick, game)
                elif bt == "rl" and game:
                    result = self.grade_run_line(pick, game)
                elif bt == "f5" and game:
                    result = self.grade_first5(pick, game)
                elif bt == "nrfi" and game:
                    result = self.grade_nrfi(pick, game)
                elif bt == "total" and game:
                    result = self.grade_total(pick, game)
                elif bt == "team_total" and game:
                    result = self.grade_team_total(pick, game)
                elif bt == "pitcher_k":
                    pid = pick.get("player_id")
                    if pid in player_logs:
                        result = self.grade_pitcher_k_prop(pick, player_logs[pid])
                elif bt == "batter_prop":
                    pid = pick.get("player_id")
                    if pid in player_logs:
                        result = self.grade_batter_prop(pick, player_logs[pid])
            except Exception as e:
                result = "ERROR"
                pick["error"] = str(e)

            pick["result"] = result
            pick["settled_at"] = datetime.now().isoformat()
            settled.append(pick)
        return settled

    @staticmethod
    def record_summary(settled):
        """Compute W-L-P record from settled picks."""
        wins = sum(1 for p in settled if p["result"] == "WIN")
        losses = sum(1 for p in settled if p["result"] == "LOSS")
        pushes = sum(1 for p in settled if p["result"] == "PUSH")
        voids = sum(1 for p in settled if p["result"] in ("VOID", "ERROR"))
        total = wins + losses
        return {
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "voids": voids,
            "total_graded": total,
            "win_pct": round(wins / total * 100, 1) if total else 0,
            "record": f"{wins}-{losses}-{pushes}",
        }

    def to_json(self, data, path=None):
        output = json.dumps(data, indent=2, default=str)
        if path:
            with open(path, "w") as f:
                f.write(output)
        return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MLB Settle Engine")
    parser.add_argument("--date", type=str, default=None)
    parser.add_argument("--picks", type=str, default=None)
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    settle_date = args.date or (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    engine = MLBSettleEngine()

    print(f"MLB Settle Engine - {settle_date}")

    if args.picks:
        with open(args.picks) as f:
            picks = json.load(f)
        print(f"Loaded {len(picks)} picks from {args.picks}")
        settled = engine.settle_date(settle_date, picks)
        summary = engine.record_summary(settled)
        print(f"RESULTS: {summary['record']} ({summary['win_pct']}%)")
        if args.output:
            engine.to_json({"date": settle_date, "summary": summary, "picks": settled}, args.output)
            print(f"Saved to {args.output}")
    else:
        print("No picks file provided. Running in demo mode...")
        games = engine.game_scraper.fetch_schedule(settle_date)
        print(f"Found {len(games)} completed games on {settle_date}")
        for g in games:
            print(f"  {g['away_team']} {g['away_score']} @ {g['home_team']} {g['home_score']}")
        print(f"To settle: python mlb_settle_engine.py --date {settle_date} --picks picks.json")
