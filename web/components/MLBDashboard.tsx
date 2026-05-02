"use client";

import { useEffect, useState } from "react";
import { MLBDailyData, TabKey } from "../types";
import { TabTable } from "./TabTable";

const TAB_ORDER: TabKey[] = [
  "todays_card",
  "moneyline",
  "run_line",
  "totals",
  "first_5",
  "first_inning",
  "team_totals",
  "backtest",
];

const DEFAULT_DATA_URL = "/data/mlb/mlb_daily.json";

interface Props {
  /** Path or URL to mlb_daily.json. Defaults to /data/mlb/mlb_daily.json. */
  dataUrl?: string;
}

export function MLBDashboard({ dataUrl = DEFAULT_DATA_URL }: Props) {
  const [data, setData] = useState<MLBDailyData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<TabKey>("todays_card");

  useEffect(() => {
    let cancelled = false;
    fetch(dataUrl, { cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(String(e)));
    return () => {
      cancelled = true;
    };
  }, [dataUrl]);

  if (error) {
    return (
      <div className="p-6 text-red-700 bg-red-50 rounded">
        Failed to load <code>{dataUrl}</code>: {error}
      </div>
    );
  }
  if (!data) {
    return <div className="p-6 text-zinc-500">Loading MLB spreadsheet…</div>;
  }

  const tab = data.tabs[active];
  const overall = data.backtest.overall;

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold">MLB Daily — {data.today}</h2>
          <p className="text-sm text-zinc-500">
            {data.counts.slate_games} games on the slate ·{" "}
            {data.counts.backfill_games} games of backfill ·{" "}
            odds via {data.odds_source}
          </p>
        </div>
        <div className="text-sm text-zinc-600">
          Backtest:{" "}
          <span className="font-semibold">
            {overall.bets} bets · {overall.hit_rate.toFixed(1)}% · {" "}
            {overall.units_pl >= 0 ? "+" : ""}
            {overall.units_pl.toFixed(2)}u ({overall.roi_pct.toFixed(2)}% ROI)
          </span>
        </div>
      </header>

      <nav className="flex flex-wrap gap-1 border-b border-zinc-200">
        {TAB_ORDER.map((key) => (
          <button
            key={key}
            onClick={() => setActive(key)}
            className={
              "px-3 py-2 text-sm rounded-t " +
              (active === key
                ? "bg-zinc-900 text-white"
                : "bg-zinc-100 text-zinc-700 hover:bg-zinc-200")
            }
          >
            {data.tabs[key].title}
          </button>
        ))}
      </nav>

      <TabTable tab={tab} />

      <footer className="text-xs text-zinc-400 pt-4 border-t border-zinc-100">
        Generated {data.generated_at} · Source: statsapi.mlb.com (game data) +{" "}
        {data.odds_source} (lines)
      </footer>
    </div>
  );
}
