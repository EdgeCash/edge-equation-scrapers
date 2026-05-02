"use client";

import { TierBadge, tierFromEdge } from "./TierBadge";
import type { TodaysPlay } from "../lib/types";

const BET_TYPE_LABEL: Record<string, string> = {
  moneyline: "Moneyline",
  run_line: "Run Line",
  totals: "Game Total",
  first_5: "First 5 Innings",
  first_inning: "First Inning",
  team_totals: "Team Total",
};

interface Props {
  plays: TodaysPlay[];
}

export function DailyCardTable({ plays }: Props) {
  if (!plays || plays.length === 0) {
    return null;
  }

  return (
    <>
      {/* Mobile: stacked cards */}
      <div className="sm:hidden space-y-3">
        {plays.map((p, i) => (
          <PlayCardMobile play={p} key={i} />
        ))}
      </div>

      {/* Desktop: table */}
      <div className="hidden sm:block chalk-card overflow-x-auto">
        <table className="data-table">
          <thead>
            <tr>
              <th>Tier</th>
              <th>Matchup</th>
              <th>Pick</th>
              <th>Edge</th>
              <th>Model</th>
              <th>Market</th>
              <th>Book</th>
              <th>Units</th>
            </tr>
          </thead>
          <tbody className="text-chalk-100">
            {plays.map((p, i) => (
              <PlayRow play={p} key={i} />
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function PlayRow({ play }: { play: TodaysPlay }) {
  const tier = tierFromEdge(play.edge_pct, play.kelly_pct);
  return (
    <tr>
      <td>
        <TierBadge tier={tier} size="sm" />
      </td>
      <td>
        <div className="text-chalk-50 font-medium">{play.matchup ?? "—"}</div>
        {play.starting_pitchers && (
          <div className="text-[11px] text-chalk-500 mt-0.5 max-w-[16rem] truncate">
            {play.starting_pitchers}
          </div>
        )}
      </td>
      <td>
        <div className="text-elite font-mono text-sm">{play.pick ?? "—"}</div>
        <div className="text-[10px] uppercase tracking-wider text-chalk-500 mt-0.5">
          {BET_TYPE_LABEL[play.bet_type ?? ""] ?? play.bet_type}
        </div>
      </td>
      <td className="font-mono">
        <span className={play.edge_pct && play.edge_pct > 0 ? "text-elite" : "text-chalk-300"}>
          {play.edge_pct !== undefined && play.edge_pct !== null
            ? `${play.edge_pct >= 0 ? "+" : ""}${play.edge_pct.toFixed(2)}%`
            : "—"}
        </span>
      </td>
      <td className="font-mono text-chalk-300 text-xs">
        {play.model_prob !== undefined && play.model_prob !== null
          ? `${(play.model_prob * 100).toFixed(1)}%`
          : "—"}
      </td>
      <td className="font-mono text-chalk-100">
        {formatAmerican(play.market_odds_american)}
      </td>
      <td className="text-xs text-chalk-300">{play.book ?? "—"}</td>
      <td>
        <UnitChip play={play} />
      </td>
    </tr>
  );
}

function PlayCardMobile({ play }: { play: TodaysPlay }) {
  const tier = tierFromEdge(play.edge_pct, play.kelly_pct);
  const isElite = tier === "Signal Elite";
  return (
    <article className={isElite ? "chalk-card-elite p-4" : "chalk-card p-4"}>
      <header className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wider text-chalk-500">
            {BET_TYPE_LABEL[play.bet_type ?? ""] ?? play.bet_type}
          </p>
          <p className="mt-1 text-chalk-50 font-medium">{play.matchup ?? "—"}</p>
        </div>
        <TierBadge tier={tier} size="sm" />
      </header>

      <p className="mt-3 text-elite font-mono text-base">{play.pick ?? "—"}</p>
      {play.starting_pitchers && (
        <p className="mt-1 text-xs text-chalk-500">{play.starting_pitchers}</p>
      )}

      <div className="mt-4 grid grid-cols-3 gap-3 text-sm">
        <Stat label="Edge" value={
          play.edge_pct !== undefined && play.edge_pct !== null
            ? `${play.edge_pct >= 0 ? "+" : ""}${play.edge_pct.toFixed(2)}%`
            : "—"
        } highlight={(play.edge_pct ?? 0) > 0} />
        <Stat label="Model" value={
          play.model_prob !== undefined && play.model_prob !== null
            ? `${(play.model_prob * 100).toFixed(1)}%`
            : "—"
        } />
        <Stat label="Market" value={formatAmerican(play.market_odds_american)} />
      </div>

      <div className="mt-4 flex items-center justify-between border-t border-chalkboard-700/60 pt-3">
        <span className="text-[11px] text-chalk-500">{play.book ?? "—"}</span>
        <UnitChip play={play} />
      </div>
    </article>
  );
}

function Stat({ label, value, highlight = false }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wider text-chalk-500">{label}</p>
      <p className={`mt-0.5 font-mono ${highlight ? "text-elite" : "text-chalk-100"}`}>
        {value}
      </p>
    </div>
  );
}

function UnitChip({ play }: { play: TodaysPlay }) {
  const kelly = play.kelly_pct;
  if (kelly === undefined || kelly === null) {
    return <span className="text-chalk-500 text-xs">—</span>;
  }
  const units = unitsFromKelly(kelly);
  return (
    <div className="text-right">
      <p className="font-chalk text-xl text-elite leading-none">{units}u</p>
      {play.portfolio_scaled_from !== undefined && play.portfolio_scaled_from !== null && (
        <p className="text-[9px] text-chalk-500 mt-0.5">
          (capped from {unitsFromKelly(play.portfolio_scaled_from)}u)
        </p>
      )}
    </div>
  );
}

/* ---------- helpers ---------- */

function formatAmerican(am: number | null | undefined): string {
  if (am === null || am === undefined) return "—";
  return am > 0 ? `+${am}` : `${am}`;
}

/** Map half-Kelly% to the brand's discrete unit display.
 * Mirrors BRAND_GUIDE tier table. */
function unitsFromKelly(kellyPct: number): string {
  if (kellyPct >= 4) return "3";
  if (kellyPct >= 3) return "2";
  if (kellyPct >= 1.5) return "1.5";
  if (kellyPct >= 0.75) return "1";
  if (kellyPct >= 0.25) return "0.5";
  return "0";
}
