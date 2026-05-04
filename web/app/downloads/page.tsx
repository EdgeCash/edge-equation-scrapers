import fs from "node:fs";
import path from "node:path";
import { ChalkboardBackground } from "../../components/ChalkboardBackground";

export const dynamic = "force-dynamic";

type Tier = "free" | "premium";

interface DataFile {
  filename: string;
  description: string;
  size: number;
  modified: Date | null;
  tier: Tier;
}

/**
 * Per-file metadata: short human-readable description + access tier.
 *
 * `tier` is currently always "free" but the field exists so future
 * gating (Vercel middleware checking a cookie/session, or a Stripe-
 * backed subscriber check) can filter without restructuring this page.
 */
const FILE_METADATA: Record<string, { description: string; tier: Tier }> = {
  "mlb_daily.xlsx": {
    description:
      "Comprehensive Excel workbook. Every market, every game, every projection. Includes today's gated picks, multi-season backtest, and per-market calibration. Best single download for power users.",
    tier: "free",
  },
  "todays_card.csv": {
    description:
      "Today's picks — only the bets that cleared the BRAND_GUIDE gate (≥+1% ROI on 200+ bets AND Brier <0.246 multi-season). What's also rendered on the Daily Card page.",
    tier: "free",
  },
  "mlb_daily.json": {
    description:
      "Same data as the Excel workbook in JSON form. The website's own daily-card page reads from this file.",
    tier: "free",
  },
  "moneyline.csv": {
    description:
      "Moneyline projections + edges for every game on today's slate. Currently gated off the daily card on Brier — included here so power users can see the underlying numbers.",
    tier: "free",
  },
  "run_line.csv": {
    description:
      "Run line (-1.5/+1.5) projections + edges. Multi-season backtest: 60.7% / +15.85% ROI / Brier 0.2384. Currently shipping on the daily card.",
    tier: "free",
  },
  "totals.csv": {
    description:
      "Over/under run totals projections + edges. Multi-season backtest: 55.2% / +5.22% ROI / Brier 0.2455. Currently shipping on the daily card.",
    tier: "free",
  },
  "first_5.csv": {
    description:
      "First-5-innings (F5) moneyline projections + edges. Currently gated on borderline ROI (+0.37%); included for transparency.",
    tier: "free",
  },
  "first_inning.csv": {
    description:
      "First-inning NRFI/YRFI projections + edges. Currently gated on multi-season ROI (-3.33%); single-season was a fluke.",
    tier: "free",
  },
  "team_totals.csv": {
    description:
      "Per-team-total over/under projections. Currently gated on Brier (0.2506); included for transparency.",
    tier: "free",
  },
  "picks_log.json": {
    description:
      "Every pick we've shipped, with closing-line snapshot, computed CLV, win/loss result, and units P/L. Append-only, idempotent. Source data for the track record.",
    tier: "free",
  },
  "clv_summary.json": {
    description:
      "Aggregate CLV stats — overall and per-market — recomputed every morning and after every closing-line snapshot. The truth-teller: long-run profitability tracks CLV more strongly than raw W-L.",
    tier: "free",
  },
  "backtest.csv": {
    description:
      "Multi-season backtest results by market. Used as the BRAND_GUIDE gate input — markets only ship to the daily card after passing here.",
    tier: "free",
  },
  "backtest.json": {
    description: "Same as backtest.csv in JSON form.",
    tier: "free",
  },
  "calibration.json": {
    description:
      "Calibrated standard deviations + ML logistic slope, fit from multi-season residuals. Re-fit each morning so distribution assumptions stay anchored to recent reality.",
    tier: "free",
  },
  "lines.json": {
    description:
      "Current market odds across books for today's slate. Source: The Odds API, fetched every morning before the build.",
    tier: "free",
  },
};

interface GroupLayout {
  title: string;
  description: string;
  files: string[];
}

const GROUP_LAYOUT: GroupLayout[] = [
  {
    title: "Daily Card",
    description: "Refreshed every morning by 11:00 AM ET, per BRAND_GUIDE.",
    files: ["mlb_daily.xlsx", "todays_card.csv", "mlb_daily.json"],
  },
  {
    title: "Per-Market Projections",
    description:
      "Every game on today's slate, every market — including the ones currently gated off the daily card. Useful if you want to see the underlying numbers behind the gating decisions.",
    files: [
      "moneyline.csv",
      "run_line.csv",
      "totals.csv",
      "first_5.csv",
      "first_inning.csv",
      "team_totals.csv",
    ],
  },
  {
    title: "Track Record",
    description:
      "Every pick we've shipped, graded against actual results, with closing-line value computed from the closing-snapshot cron.",
    files: ["picks_log.json", "clv_summary.json"],
  },
  {
    title: "Calibration & Backtest",
    description:
      "The numbers behind the model. Multi-season backtest results, the BRAND_GUIDE gate inputs, and the calibrated distribution constants.",
    files: ["backtest.csv", "backtest.json", "calibration.json"],
  },
  {
    title: "Live Market Data",
    description: "Today's market state at the time of this morning's build.",
    files: ["lines.json"],
  },
];

function getDataFiles(): { title: string; description: string; files: DataFile[] }[] {
  const dataDir = path.join(process.cwd(), "public", "data", "mlb");

  return GROUP_LAYOUT.map((group) => ({
    title: group.title,
    description: group.description,
    files: group.files
      .map((filename): DataFile | null => {
        const fullPath = path.join(dataDir, filename);
        const meta = FILE_METADATA[filename] ?? {
          description: "",
          tier: "free" as Tier,
        };
        try {
          const stats = fs.statSync(fullPath);
          return {
            filename,
            description: meta.description,
            tier: meta.tier,
            size: stats.size,
            modified: stats.mtime,
          };
        } catch {
          return null;
        }
      })
      .filter((f): f is DataFile => f !== null),
  }));
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatModified(d: Date | null): string {
  if (!d) return "—";
  // Use UTC to avoid server/client timezone mismatch hydration warnings.
  return d.toISOString().slice(0, 16).replace("T", " ") + "Z";
}

export default function DataPage() {
  const groups = getDataFiles();
  const totalFiles = groups.reduce((sum, g) => sum + g.files.length, 0);

  return (
    <>
      <section className="relative overflow-hidden border-b border-chalkboard-600/40">
        <ChalkboardBackground />
        <div className="relative z-10 max-w-5xl mx-auto px-4 sm:px-6 py-12 sm:py-16">
          <p className="font-chalk text-2xl text-elite/80 -rotate-1 inline-block">
            Raw Data
          </p>
          <h1 className="mt-1 text-4xl sm:text-5xl font-bold text-chalk-50">
            Spreadsheets &amp; downloads
            <span className="block text-base font-normal text-chalk-300 mt-2">
              Every CSV, JSON, and Excel artifact the model produces.
              Show-your-work transparency. Currently public — premium gating
              comes later.
            </span>
          </h1>
        </div>
      </section>

      <section className="max-w-5xl mx-auto px-4 sm:px-6 py-10 sm:py-14">
        <div className="rounded-lg border border-chalkboard-700/60 bg-chalkboard-900/40 p-5 mb-10 text-sm text-chalk-300 leading-relaxed">
          <p>
            <span className="text-chalk-100 font-semibold">{totalFiles} files</span>{" "}
            across {groups.length} sections, refreshed by the daily build cron.
            Click any filename to download. JSON and CSV are human-readable; the{" "}
            <code className="text-elite">.xlsx</code> opens in Excel /
            Numbers / Sheets.
          </p>
          <p className="mt-3">
            All artifacts are currently free to download. As we accumulate a
            longer track record + add NCAAF and other sports, this page may
            move to a subscriber tier — the underlying picks-log data here is
            the audit trail for everything we publish.
          </p>
        </div>

        {groups.map((group) => (
          <section key={group.title} className="mb-12">
            <h2 className="text-2xl font-bold text-chalk-50 mb-1">
              {group.title}
            </h2>
            <p className="text-sm text-chalk-400 mb-5 max-w-3xl">
              {group.description}
            </p>

            {group.files.length === 0 ? (
              <p className="text-sm text-chalk-500 italic">
                No files currently published in this section.
              </p>
            ) : (
              <div className="rounded-lg border border-chalkboard-700/60 bg-chalkboard-950/60 overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-chalkboard-900/60 text-chalk-300">
                    <tr>
                      <th className="text-left px-4 py-2 font-medium">File</th>
                      <th className="text-left px-4 py-2 font-medium hidden sm:table-cell">
                        Description
                      </th>
                      <th className="text-right px-4 py-2 font-medium whitespace-nowrap">
                        Size
                      </th>
                      <th className="text-right px-4 py-2 font-medium whitespace-nowrap hidden md:table-cell">
                        Updated (UTC)
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {group.files.map((file) => (
                      <tr
                        key={file.filename}
                        className="border-t border-chalkboard-700/40 hover:bg-chalkboard-900/40 transition-colors"
                      >
                        <td className="px-4 py-3 align-top">
                          <a
                            href={`/data/mlb/${file.filename}`}
                            download
                            className="font-mono text-elite hover:underline whitespace-nowrap"
                          >
                            {file.filename}
                          </a>
                          <p className="mt-1 text-xs text-chalk-400 sm:hidden">
                            {file.description}
                          </p>
                        </td>
                        <td className="px-4 py-3 text-chalk-300 hidden sm:table-cell">
                          {file.description}
                        </td>
                        <td className="px-4 py-3 text-right text-chalk-400 whitespace-nowrap align-top">
                          {formatSize(file.size)}
                        </td>
                        <td className="px-4 py-3 text-right text-chalk-500 font-mono text-xs whitespace-nowrap hidden md:table-cell align-top">
                          {formatModified(file.modified)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        ))}

        <p className="text-xs text-chalk-500 mt-12 leading-relaxed">
          File contents reflect the most recent successful daily build.
          Timestamps are filesystem mtime at the deployed Vercel snapshot —
          they update each time the data files commit to main and the site
          rebuilds.
        </p>
      </section>
    </>
  );
}
