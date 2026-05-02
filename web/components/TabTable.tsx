import { BetTab, KellyAdvice } from "../types";
import { KellyBadge } from "./KellyBadge";

function formatCell(col: string, value: unknown): React.ReactNode {
  if (value === null || value === undefined || value === "") return "—";
  if (col === "kelly_advice") {
    return <KellyBadge advice={value as KellyAdvice} />;
  }
  if (col === "kelly_pct" && typeof value === "number") {
    return `${value.toFixed(2)}%`;
  }
  if (col.endsWith("_prob") && typeof value === "number") {
    return `${(value * 100).toFixed(1)}%`;
  }
  if (col === "hit_rate" || col === "roi_pct") {
    return `${(value as number).toFixed(1)}%`;
  }
  if (col === "units_pl" && typeof value === "number") {
    const sign = value >= 0 ? "+" : "";
    return `${sign}${value.toFixed(2)}u`;
  }
  if (col === "market_odds_american" && typeof value === "number") {
    return value > 0 ? `+${value}` : `${value}`;
  }
  return String(value);
}

export function TabTable({ tab }: { tab: BetTab }) {
  return (
    <div className="space-y-6">
      <Section
        title={tab.projection_section_title ?? "Projections"}
        columns={tab.projection_columns}
        rows={tab.projections}
        accent="emerald"
      />
      <Section
        title={tab.backfill_section_title ?? "Backfill"}
        columns={tab.backfill_columns}
        rows={tab.backfill}
        accent="zinc"
      />
    </div>
  );
}

function Section({
  title,
  columns,
  rows,
  accent,
}: {
  title: string;
  columns: string[];
  rows: Record<string, unknown>[];
  accent: "emerald" | "zinc";
}) {
  const headerBg =
    accent === "emerald" ? "bg-emerald-700 text-white" : "bg-zinc-700 text-white";
  return (
    <div>
      <h3 className={`px-3 py-2 text-sm font-semibold ${headerBg} rounded-t`}>
        {title}
      </h3>
      <div className="overflow-x-auto border border-zinc-200 rounded-b">
        <table className="min-w-full text-sm">
          <thead className="bg-zinc-50">
            <tr>
              {columns.map((c) => (
                <th key={c} className="px-3 py-2 text-left font-medium text-zinc-600">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="px-3 py-4 text-zinc-400 italic">
                  No rows
                </td>
              </tr>
            )}
            {rows.map((row, i) => (
              <tr key={i} className="odd:bg-white even:bg-zinc-50">
                {columns.map((c) => (
                  <td key={c} className="px-3 py-1.5 whitespace-nowrap">
                    {formatCell(c, row[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
