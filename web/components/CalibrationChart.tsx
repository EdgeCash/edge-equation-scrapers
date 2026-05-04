import type { PickLogEntry } from "../lib/types";

/**
 * Reliability diagram (a.k.a. calibration plot).
 *
 * Bins published picks by their predicted probability, computes the
 * actual win rate within each bin, and renders predicted-vs-actual.
 * Perfect calibration lies on the diagonal y = x.
 *
 * Why this matters: a model that says "70%" should win 70% of the
 * time across all its 70% picks. If our 70% bucket actually wins 60%,
 * we're systematically over-confident. The reliability diagram shows
 * that drift in one chart — the brand-promise version of "show your
 * work."
 *
 * Pure SVG, no chart library — keeps the bundle small and the rendering
 * deterministic. Server-rendered as part of the page.
 */

interface Bin {
  // Inclusive lower, exclusive upper. Last bin is inclusive on both.
  lo: number;
  hi: number;
  n: number;            // total picks in bin (incl. PUSH)
  graded: number;       // picks with WIN or LOSS (excl. PUSH)
  wins: number;
  predicted_avg: number; // mean predicted prob across picks in bin
  actual_hit_rate: number; // wins / graded
}

const BINS: { lo: number; hi: number; label: string }[] = [
  { lo: 0.0,  hi: 0.55, label: "<55%" },
  { lo: 0.55, hi: 0.60, label: "55-60%" },
  { lo: 0.60, hi: 0.65, label: "60-65%" },
  { lo: 0.65, hi: 0.70, label: "65-70%" },
  { lo: 0.70, hi: 0.75, label: "70-75%" },
  { lo: 0.75, hi: 0.80, label: "75-80%" },
  { lo: 0.80, hi: 1.01, label: ">80%" },
];

function buildBins(picks: PickLogEntry[]): Bin[] {
  return BINS.map(({ lo, hi }) => {
    const inBin = picks.filter(
      (p) =>
        typeof p.model_prob === "number" &&
        p.model_prob >= lo &&
        p.model_prob < hi
    );
    const graded = inBin.filter((p) => p.result === "WIN" || p.result === "LOSS");
    const wins = inBin.filter((p) => p.result === "WIN").length;
    const predicted_avg =
      inBin.length === 0
        ? (lo + hi) / 2
        : inBin.reduce((s, p) => s + (p.model_prob ?? 0), 0) / inBin.length;
    return {
      lo,
      hi,
      n: inBin.length,
      graded: graded.length,
      wins,
      predicted_avg,
      actual_hit_rate: graded.length === 0 ? 0 : wins / graded.length,
    };
  });
}

export function CalibrationChart({ picks }: { picks: PickLogEntry[] }) {
  // Filter to graded picks only — un-resolved picks have no answer yet.
  const graded = picks.filter(
    (p) =>
      typeof p.model_prob === "number" &&
      (p.result === "WIN" || p.result === "LOSS")
  );

  if (graded.length === 0) {
    return (
      <div className="chalk-card p-6 text-center">
        <p className="text-sm text-chalk-300">
          Calibration chart will appear once we have graded picks with
          predicted probabilities. Right now we have{" "}
          <span className="font-mono text-chalk-100">{picks.length}</span>{" "}
          total picks, none yet graded.
        </p>
      </div>
    );
  }

  const bins = buildBins(graded);
  const populated = bins.filter((b) => b.graded > 0);

  // SVG layout
  const W = 540;
  const H = 360;
  const PADDING_L = 56;
  const PADDING_R = 16;
  const PADDING_T = 16;
  const PADDING_B = 50;
  const plotW = W - PADDING_L - PADDING_R;
  const plotH = H - PADDING_T - PADDING_B;

  // Plot scales: x = predicted prob (0-1), y = actual rate (0-1)
  const xScale = (v: number) => PADDING_L + v * plotW;
  const yScale = (v: number) => PADDING_T + (1 - v) * plotH;

  // Marker radius scales with sample size (2-12px) so tiny bins look
  // appropriately tentative and large bins anchor the eye.
  const maxN = Math.max(...populated.map((b) => b.graded), 1);
  const radius = (n: number) => {
    if (maxN === 1) return 6;
    const t = Math.sqrt(n / maxN);
    return 3 + t * 10;
  };

  // Gridlines every 0.1
  const gridTicks = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1];

  return (
    <div className="chalk-card p-5">
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <h3 className="text-lg font-semibold text-chalk-50">
          Calibration: predicted vs. actual
        </h3>
        <p className="text-xs text-chalk-500 font-mono">
          {graded.length} graded picks
        </p>
      </div>
      <p className="mt-1 text-xs text-chalk-400 max-w-2xl">
        Each dot is a probability bucket. The diagonal is perfect
        calibration — a 70% pick wins 70% of the time. Above the line:
        we&apos;re under-confident; below: over-confident. Larger dots = more samples.
      </p>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label="Calibration reliability diagram"
        className="mt-4 w-full h-auto"
      >
        {/* Background gridlines */}
        {gridTicks.map((t) => (
          <g key={`grid-${t}`}>
            <line
              x1={xScale(t)}
              y1={PADDING_T}
              x2={xScale(t)}
              y2={PADDING_T + plotH}
              stroke="#1f2937"
              strokeWidth={0.5}
            />
            <line
              x1={PADDING_L}
              y1={yScale(t)}
              x2={PADDING_L + plotW}
              y2={yScale(t)}
              stroke="#1f2937"
              strokeWidth={0.5}
            />
          </g>
        ))}

        {/* Diagonal: perfect calibration */}
        <line
          x1={xScale(0)}
          y1={yScale(0)}
          x2={xScale(1)}
          y2={yScale(1)}
          stroke="#475569"
          strokeWidth={1}
          strokeDasharray="4 4"
        />

        {/* Axis labels */}
        {[0, 0.25, 0.5, 0.75, 1].map((t) => (
          <g key={`xtick-${t}`}>
            <text
              x={xScale(t)}
              y={H - PADDING_B + 18}
              textAnchor="middle"
              fontSize="11"
              fill="#94a3b8"
              fontFamily="ui-monospace, monospace"
            >
              {Math.round(t * 100)}%
            </text>
          </g>
        ))}
        {[0, 0.25, 0.5, 0.75, 1].map((t) => (
          <g key={`ytick-${t}`}>
            <text
              x={PADDING_L - 8}
              y={yScale(t) + 4}
              textAnchor="end"
              fontSize="11"
              fill="#94a3b8"
              fontFamily="ui-monospace, monospace"
            >
              {Math.round(t * 100)}%
            </text>
          </g>
        ))}

        {/* Axis titles */}
        <text
          x={PADDING_L + plotW / 2}
          y={H - 6}
          textAnchor="middle"
          fontSize="11"
          fill="#cbd5e1"
        >
          Predicted probability
        </text>
        <text
          x={14}
          y={PADDING_T + plotH / 2}
          textAnchor="middle"
          fontSize="11"
          fill="#cbd5e1"
          transform={`rotate(-90, 14, ${PADDING_T + plotH / 2})`}
        >
          Actual hit rate
        </text>

        {/* Calibration dots */}
        {populated.map((b, i) => {
          const x = xScale(b.predicted_avg);
          const y = yScale(b.actual_hit_rate);
          const r = radius(b.graded);
          // Color: distance from diagonal. Closer = better calibrated.
          const drift = Math.abs(b.predicted_avg - b.actual_hit_rate);
          const color =
            drift < 0.03 ? "#38bdf8" : drift < 0.08 ? "#84cc16" : "#f59e0b";
          return (
            <g key={`dot-${i}`}>
              <circle
                cx={x}
                cy={y}
                r={r}
                fill={color}
                fillOpacity={0.75}
                stroke={color}
                strokeWidth={1.5}
              />
              <text
                x={x}
                y={y - r - 4}
                textAnchor="middle"
                fontSize="9"
                fontFamily="ui-monospace, monospace"
                fill="#cbd5e1"
              >
                n={b.graded}
              </text>
            </g>
          );
        })}
      </svg>

      <div className="mt-4 overflow-x-auto">
        <table className="data-table text-xs">
          <thead>
            <tr>
              <th>Bucket</th>
              <th className="text-right">Picks (graded)</th>
              <th className="text-right">Predicted avg</th>
              <th className="text-right">Actual rate</th>
              <th className="text-right">Drift</th>
            </tr>
          </thead>
          <tbody className="text-chalk-200">
            {bins.map((b, i) => {
              if (b.graded === 0) {
                return (
                  <tr key={`row-${i}`} className="text-chalk-500">
                    <td>{BINS[i].label}</td>
                    <td className="text-right font-mono">— ({b.n})</td>
                    <td className="text-right font-mono">—</td>
                    <td className="text-right font-mono">—</td>
                    <td className="text-right font-mono">—</td>
                  </tr>
                );
              }
              const drift = b.actual_hit_rate - b.predicted_avg;
              return (
                <tr key={`row-${i}`}>
                  <td className="text-chalk-100">{BINS[i].label}</td>
                  <td className="text-right font-mono text-chalk-300">
                    {b.graded} ({b.n})
                  </td>
                  <td className="text-right font-mono">
                    {(b.predicted_avg * 100).toFixed(1)}%
                  </td>
                  <td className="text-right font-mono">
                    {(b.actual_hit_rate * 100).toFixed(1)}%
                  </td>
                  <td
                    className={`text-right font-mono ${
                      Math.abs(drift) < 0.03
                        ? "text-elite"
                        : drift > 0
                        ? "text-strong"
                        : "text-nosignal"
                    }`}
                  >
                    {drift >= 0 ? "+" : ""}
                    {(drift * 100).toFixed(1)} pts
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-[11px] text-chalk-500">
        Drift = (actual − predicted). Positive = model under-predicted; negative = over-predicted.
        Buckets with zero graded picks show their total count in parens.
      </p>
    </div>
  );
}
