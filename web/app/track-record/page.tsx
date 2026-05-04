import { headers } from "next/headers";
import { ChalkboardBackground } from "../../components/ChalkboardBackground";
import { CalibrationChart } from "../../components/CalibrationChart";
import {
  getDailyData,
  getPicksLog,
  summarizePicks,
  lastNDaysPicks,
  type BacktestSummaryRow,
  type PickLogEntry,
} from "../../lib/types";

export const dynamic = "force-dynamic";

const BET_TYPE_LABEL: Record<string, string> = {
  moneyline: "Moneyline",
  run_line: "Run Line",
  totals: "Game Total",
  first_5: "First 5 Innings",
  first_inning: "First Inning",
  team_totals: "Team Total",
  all: "All markets",
};

export default async function TrackRecordPage() {
  const h = await headers();
  const host = h.get("host");
  const proto = h.get("x-forwarded-proto") ?? "https";
  const origin = host ? `${proto}://${host}` : undefined;

  const [data, picksLog] = await Promise.all([
    getDailyData(origin),
    getPicksLog(origin),
  ]);

  if (!data) {
    return (
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-20 text-center">
        <h1 className="text-3xl font-bold text-chalk-50">
          Track record unavailable
        </h1>
        <p className="mt-3 text-chalk-300">
          Couldn&apos;t load <code>/data/mlb/mlb_daily.json</code>.
        </p>
      </section>
    );
  }

  const overall = data.backtest.overall;
  const byType = data.backtest.summary_by_bet_type;
  const dailyPL = data.backtest.daily_pl;

  // Published-picks summary (real-money simulation: every play we
  // actually publish, graded after game completion). Distinct from
  // the season-long backtest above which grades every game-line at
  // flat -110 regardless of whether we'd publish it.
  const allPicks = picksLog?.picks ?? [];
  const publishedAll = summarizePicks(allPicks);
  const published30d = summarizePicks(lastNDaysPicks(allPicks, 30));
  const recentResolved = allPicks
    .filter((p) => p.result === "WIN" || p.result === "LOSS" || p.result === "PUSH")
    .sort((a, b) => (b.date > a.date ? 1 : -1))
    .slice(0, 20);

  return (
    <>
      <section className="relative overflow-hidden border-b border-chalkboard-600/40">
        <ChalkboardBackground />
        <div className="relative z-10 max-w-7xl mx-auto px-4 sm:px-6 py-12 sm:py-16">
          <p className="font-chalk text-2xl text-elite/80 -rotate-1 inline-block">
            Public ledger
          </p>
          <h1 className="mt-1 text-4xl sm:text-5xl font-bold text-chalk-50">
            Track Record
          </h1>
          <p className="mt-6 text-chalk-300 max-w-2xl">
            Season-to-date backtest, flat 1 unit at -110 across all markets.
            We publish ROI, hit rate, and Brier score per market — the markets
            that aren&apos;t profitable yet stay visible here even when they get
            gated off the daily card.
          </p>
        </div>
      </section>

      <PublishedPicks
        all={publishedAll}
        last30={published30d}
        recent={recentResolved}
      />

      <section className="max-w-7xl mx-auto px-4 sm:px-6 pt-12 pb-2">
        <h2 className="text-xl font-semibold text-chalk-50">
          Calibration check
        </h2>
        <p className="mt-2 text-sm text-chalk-300 max-w-3xl">
          A 70% pick should win 70% of the time. The chart below bins our
          published picks by predicted probability and shows the actual
          hit rate. Dots near the diagonal mean the model&apos;s
          confidence numbers are honest.
        </p>
      </section>

      <section className="max-w-7xl mx-auto px-4 sm:px-6 pb-6">
        <CalibrationChart picks={allPicks} />
      </section>

      <section className="max-w-7xl mx-auto px-4 sm:px-6 pt-12 pb-2">
        <h2 className="text-xl font-semibold text-chalk-50">
          Backtest (season-to-date, every game-line at flat -110)
        </h2>
        <p className="mt-2 text-sm text-chalk-300 max-w-3xl">
          Independent of what we publish. Grades every line we could have
          played as a calibration check on the model itself. The market gate
          uses these numbers to decide what's eligible for the daily card.
        </p>
      </section>

      <section className="max-w-7xl mx-auto px-4 sm:px-6 py-6 grid grid-cols-2 sm:grid-cols-4 gap-4">
        <KPI
          label="Backtest bets"
          value={overall.bets.toLocaleString()}
        />
        <KPI
          label="Hit rate"
          value={`${overall.hit_rate.toFixed(1)}%`}
        />
        <KPI
          label="Units P&L"
          value={`${overall.units_pl >= 0 ? "+" : ""}${overall.units_pl.toFixed(2)}u`}
          highlight={overall.units_pl >= 0}
        />
        <KPI
          label="ROI"
          value={`${overall.roi_pct >= 0 ? "+" : ""}${overall.roi_pct.toFixed(2)}%`}
          highlight={overall.roi_pct >= 0}
        />
      </section>

      <section className="max-w-7xl mx-auto px-4 sm:px-6 py-6">
        <h2 className="text-xl font-semibold text-chalk-50 mb-4">By market</h2>
        <div className="chalk-card overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th>Market</th>
                <th className="text-right">Bets</th>
                <th className="text-right">Hit %</th>
                <th className="text-right">Units</th>
                <th className="text-right">ROI</th>
                <th className="text-right">Brier</th>
                <th>Gate</th>
              </tr>
            </thead>
            <tbody className="text-chalk-100">
              {byType
                .filter((r) => r.scope === "BY TYPE")
                .map((r) => (
                  <MarketRow key={r.bet_type} row={r} />
                ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-chalk-500 max-w-3xl">
          A market clears the gate when it shows ≥+1% ROI AND Brier &lt; 0.246
          over its rolling 200+ bet backtest. Failing the gate doesn&apos;t hide
          the market — it just keeps it off the daily card while we work on it.
        </p>
      </section>

      <section className="max-w-7xl mx-auto px-4 sm:px-6 py-10">
        <h2 className="text-xl font-semibold text-chalk-50 mb-4">
          Daily P&amp;L (most recent first)
        </h2>
        <div className="chalk-card overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th>Date</th>
                <th className="text-right">Daily units</th>
                <th className="text-right">Cumulative</th>
              </tr>
            </thead>
            <tbody className="text-chalk-100">
              {dailyPL.slice(0, 30).map((d) => (
                <tr key={d.date}>
                  <td className="font-mono text-chalk-300">{d.date}</td>
                  <td
                    className={`text-right font-mono ${
                      d.daily_units >= 0 ? "text-strong" : "text-nosignal"
                    }`}
                  >
                    {d.daily_units >= 0 ? "+" : ""}
                    {d.daily_units.toFixed(2)}u
                  </td>
                  <td
                    className={`text-right font-mono ${
                      d.cumulative_units >= 0 ? "text-strong" : "text-nosignal"
                    }`}
                  >
                    {d.cumulative_units >= 0 ? "+" : ""}
                    {d.cumulative_units.toFixed(2)}u
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function KPI({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div className="chalk-card p-5">
      <p className="text-xs uppercase tracking-wider text-chalk-500">{label}</p>
      <p
        className={`mt-2 text-2xl font-mono ${
          highlight === true
            ? "text-strong"
            : highlight === false
            ? "text-nosignal"
            : "text-chalk-50"
        }`}
      >
        {value}
      </p>
    </div>
  );
}

function PublishedPicks({
  all,
  last30,
  recent,
}: {
  all: ReturnType<typeof summarizePicks>;
  last30: ReturnType<typeof summarizePicks>;
  recent: PickLogEntry[];
}) {
  // If there are no published picks at all (e.g. cold start, market gate
  // keeping the card empty), show an honest empty-state rather than zeros.
  const hasAny = all.n > 0;

  return (
    <section className="max-w-7xl mx-auto px-4 sm:px-6 pt-10">
      <div className="flex items-baseline justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-xl font-semibold text-chalk-50">
            Published Picks
          </h2>
          <p className="mt-1 text-sm text-chalk-300 max-w-3xl">
            Every play that&apos;s actually shipped on the daily card,
            graded after game completion. Real-money simulation at the
            prices we took. CLV captured at first pitch.
          </p>
        </div>
        {hasAny && all.mean_clv_pct !== null && (
          <p className="text-xs text-chalk-500 font-mono">
            Mean CLV (full history): {all.mean_clv_pct >= 0 ? "+" : ""}
            {all.mean_clv_pct}% over {all.n_with_clv} snapped picks
          </p>
        )}
      </div>

      {!hasAny && (
        <div className="mt-6 chalk-card p-8 text-center">
          <p className="font-chalk text-2xl text-elite/80 -rotate-2 inline-block">
            No picks shipped yet.
          </p>
          <p className="mt-3 text-chalk-300 max-w-2xl mx-auto">
            Once the model clears the BRAND_GUIDE market gate (≥+1% ROI
            AND Brier &lt; 0.246 over 200+ bets) the daily card will start
            publishing plays here.
          </p>
        </div>
      )}

      {hasAny && (
        <>
          <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-6">
            <PublishedPanel title="30-day rolling" stats={last30} accent="elite" />
            <PublishedPanel title="Full history" stats={all} accent="default" />
          </div>

          {recent.length > 0 && (
            <div className="mt-8">
              <h3 className="text-sm font-semibold uppercase tracking-wider text-chalk-300 mb-3">
                Recently resolved
              </h3>
              <div className="chalk-card overflow-x-auto">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Matchup</th>
                      <th>Pick</th>
                      <th className="text-right">CLV</th>
                      <th className="text-right">Result</th>
                      <th className="text-right">Units</th>
                    </tr>
                  </thead>
                  <tbody className="text-chalk-100">
                    {recent.map((p) => (
                      <tr key={p.pick_id}>
                        <td className="font-mono text-chalk-300 text-xs">{p.date}</td>
                        <td className="text-chalk-50">{p.matchup}</td>
                        <td className="font-mono text-elite text-sm">{p.pick}</td>
                        <td className="text-right font-mono text-xs">
                          {p.clv_pct === null || p.clv_pct === undefined ? (
                            <span className="text-chalk-500">—</span>
                          ) : (
                            <span className={p.clv_pct >= 0 ? "text-elite" : "text-chalk-300"}>
                              {p.clv_pct >= 0 ? "+" : ""}
                              {p.clv_pct.toFixed(2)}%
                            </span>
                          )}
                        </td>
                        <td className="text-right">
                          <ResultBadge result={p.result ?? null} />
                        </td>
                        <td
                          className={`text-right font-mono ${
                            (p.units ?? 0) > 0 ? "text-strong" :
                            (p.units ?? 0) < 0 ? "text-nosignal" : "text-chalk-300"
                          }`}
                        >
                          {p.units !== null && p.units !== undefined
                            ? `${p.units >= 0 ? "+" : ""}${p.units.toFixed(2)}u`
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function PublishedPanel({
  title,
  stats,
  accent,
}: {
  title: string;
  stats: ReturnType<typeof summarizePicks>;
  accent: "elite" | "default";
}) {
  const cardCls = accent === "elite" ? "chalk-card-elite p-6" : "chalk-card p-6";
  const isPositive = stats.units_pl >= 0;
  return (
    <div className={cardCls}>
      <p className="text-xs uppercase tracking-wider text-chalk-500">{title}</p>
      <div className="mt-3 grid grid-cols-2 gap-4">
        <div>
          <p className="text-xs text-chalk-300">Picks</p>
          <p className="font-mono text-xl text-chalk-50">
            {stats.n}
            <span className="text-xs text-chalk-500 ml-2">({stats.graded} graded)</span>
          </p>
        </div>
        <div>
          <p className="text-xs text-chalk-300">Hit rate</p>
          <p className="font-mono text-xl text-chalk-50">
            {stats.graded ? `${stats.hit_rate}%` : "—"}
          </p>
        </div>
        <div>
          <p className="text-xs text-chalk-300">Units P&amp;L</p>
          <p className={`font-mono text-xl ${isPositive ? "text-strong" : "text-nosignal"}`}>
            {stats.units_pl >= 0 ? "+" : ""}
            {stats.units_pl.toFixed(2)}u
          </p>
        </div>
        <div>
          <p className="text-xs text-chalk-300">ROI</p>
          <p className={`font-mono text-xl ${isPositive ? "text-strong" : "text-nosignal"}`}>
            {stats.roi_pct >= 0 ? "+" : ""}
            {stats.roi_pct.toFixed(2)}%
          </p>
        </div>
      </div>
      {stats.mean_clv_pct !== null && (
        <div className="mt-4 pt-3 border-t border-chalkboard-700">
          <p className="text-xs text-chalk-300">Mean CLV ({stats.n_with_clv} snapped)</p>
          <p
            className={`font-mono text-lg ${
              stats.mean_clv_pct >= 0 ? "text-elite" : "text-chalk-300"
            }`}
          >
            {stats.mean_clv_pct >= 0 ? "+" : ""}
            {stats.mean_clv_pct}%
          </p>
        </div>
      )}
    </div>
  );
}

function ResultBadge({ result }: { result: "WIN" | "LOSS" | "PUSH" | null }) {
  if (result === null) return <span className="text-chalk-500 text-xs">—</span>;
  const cls = result === "WIN"
    ? "bg-strong/15 text-strong border border-strong/40"
    : result === "LOSS"
    ? "bg-nosignal/15 text-nosignal border border-nosignal/40"
    : "bg-chalk-500/15 text-chalk-300 border border-chalk-500/40";
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider ${cls}`}>
      {result}
    </span>
  );
}

function MarketRow({ row }: { row: BacktestSummaryRow }) {
  const passes =
    row.bets >= 200 &&
    row.roi_pct >= 1 &&
    row.brier !== null &&
    row.brier !== undefined &&
    row.brier < 0.246;
  return (
    <tr>
      <td className="text-chalk-50">
        {BET_TYPE_LABEL[row.bet_type] ?? row.bet_type}
      </td>
      <td className="text-right font-mono text-chalk-300">{row.bets}</td>
      <td className="text-right font-mono">{row.hit_rate.toFixed(1)}%</td>
      <td
        className={`text-right font-mono ${
          row.units_pl >= 0 ? "text-strong" : "text-nosignal"
        }`}
      >
        {row.units_pl >= 0 ? "+" : ""}
        {row.units_pl.toFixed(2)}u
      </td>
      <td
        className={`text-right font-mono ${
          row.roi_pct >= 0 ? "text-strong" : "text-nosignal"
        }`}
      >
        {row.roi_pct >= 0 ? "+" : ""}
        {row.roi_pct.toFixed(2)}%
      </td>
      <td className="text-right font-mono text-chalk-300">
        {row.brier !== null && row.brier !== undefined
          ? row.brier.toFixed(4)
          : "—"}
      </td>
      <td>
        {passes ? (
          <span className="inline-flex items-center gap-1.5 text-xs text-elite">
            <span className="h-1.5 w-1.5 rounded-full bg-elite" /> Active
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 text-xs text-chalk-500">
            <span className="h-1.5 w-1.5 rounded-full bg-chalk-500" /> Gated
          </span>
        )}
      </td>
    </tr>
  );
}
