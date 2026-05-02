import { headers } from "next/headers";
import { ChalkboardBackground } from "../../components/ChalkboardBackground";
import { getDailyData, type BacktestSummaryRow } from "../../lib/types";

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

  const data = await getDailyData(origin);

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

      <section className="max-w-7xl mx-auto px-4 sm:px-6 py-10 grid grid-cols-2 sm:grid-cols-4 gap-4">
        <KPI
          label="Total bets"
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
