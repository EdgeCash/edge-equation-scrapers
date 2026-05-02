import Link from "next/link";
import { headers } from "next/headers";
import { ChalkboardBackground } from "../../components/ChalkboardBackground";
import { DailyCardTable } from "../../components/DailyCardTable";
import { getDailyData, type TodaysPlay } from "../../lib/types";

export const dynamic = "force-dynamic";

export default async function DailyCardPage() {
  const h = await headers();
  const host = h.get("host");
  const proto = h.get("x-forwarded-proto") ?? "https";
  const origin = host ? `${proto}://${host}` : undefined;

  const data = await getDailyData(origin);

  if (!data) {
    return <DataUnavailable />;
  }

  const card = data.tabs.todays_card;
  const plays = (card?.projections ?? []) as TodaysPlay[];
  const fadeList = (card?.backfill ?? []) as TodaysPlay[];
  const generatedAt = data.generated_at;
  const today = data.today;
  const counts = data.counts;
  const oddsSource = data.odds_source;

  return (
    <>
      <section className="relative overflow-hidden border-b border-chalkboard-600/40">
        <ChalkboardBackground />
        <div className="relative z-10 max-w-7xl mx-auto px-4 sm:px-6 py-12 sm:py-16">
          <p className="font-chalk text-2xl text-elite/80 -rotate-1 inline-block">
            Today
          </p>
          <h1 className="mt-1 text-4xl sm:text-5xl font-bold text-chalk-50">
            {today}
            <span className="block text-base font-normal text-chalk-300 mt-2">
              {plays.length === 0
                ? "No plays today. The math says pass."
                : `${plays.length} ${plays.length === 1 ? "play" : "plays"} on the card.`}
            </span>
          </h1>

          <p className="mt-6 text-sm text-chalk-300 max-w-2xl">
            {counts.slate_games} games on the slate · {counts.priced_games} priced via{" "}
            <span className="text-chalk-100">{oddsSource}</span> · published{" "}
            <time dateTime={generatedAt}>
              {new Date(generatedAt).toLocaleString("en-US", {
                timeZone: "America/New_York",
                hour: "numeric",
                minute: "2-digit",
                month: "short",
                day: "numeric",
              })}{" "}
              ET
            </time>
          </p>
        </div>
      </section>

      <section className="max-w-7xl mx-auto px-4 sm:px-6 py-10 sm:py-14">
        {plays.length > 0 ? (
          <DailyCardTable plays={plays} />
        ) : (
          <EmptyCard
            backfillTitle={card?.backfill_section_title}
            fadeList={fadeList}
          />
        )}

        {plays.length > 0 && (
          <p className="mt-6 text-xs text-chalk-500 max-w-2xl">
            Tier and unit count are derived from the model&apos;s edge over the
            current best market price. Picks below the per-market edge threshold
            are excluded from this card and listed in the FADE / SKIP section in
            the daily backtest output. CLV is captured at first pitch and shown
            on the{" "}
            <Link href="/track-record" className="text-elite hover:underline">
              track record
            </Link>
            .
          </p>
        )}
      </section>
    </>
  );
}

/* ---------- Empty card ---------- */

function EmptyCard({
  backfillTitle,
  fadeList,
}: {
  backfillTitle?: string;
  fadeList: TodaysPlay[];
}) {
  return (
    <div className="chalk-card p-8 sm:p-12 text-center">
      <p className="font-chalk text-3xl text-elite/80 -rotate-2 inline-block">
        Some days, no play is the play.
      </p>
      <h2 className="mt-4 text-2xl font-bold text-chalk-50">
        Today&apos;s Card is intentionally empty.
      </h2>
      <p className="mt-3 text-chalk-300 max-w-2xl mx-auto leading-relaxed">
        Per our market gating rule, a market only ships when its rolling
        backtest sample shows ≥+1% ROI <em>and</em> Brier under 0.246. Today,
        none of our markets clear both bars. Volume without edge is how
        bankrolls die.
      </p>

      {backfillTitle && (
        <div className="mt-8 text-left max-w-2xl mx-auto bg-chalkboard-900/60 border border-chalkboard-700 rounded-md p-4">
          <p className="text-xs uppercase tracking-wider text-chalk-500 mb-2">
            Why each market was excluded
          </p>
          <p className="text-sm text-chalk-300 font-mono leading-relaxed">
            {backfillTitle}
          </p>
        </div>
      )}

      <div className="mt-8 flex flex-wrap justify-center gap-3">
        <Link href="/track-record" className="btn-ghost">
          See track record
        </Link>
        <Link href="/methodology" className="btn-ghost">
          Read the methodology
        </Link>
      </div>

      {fadeList.length > 0 && (
        <p className="mt-6 text-[11px] text-chalk-500">
          {fadeList.length} sub-threshold leans not published.
        </p>
      )}
    </div>
  );
}

/* ---------- Error state ---------- */

function DataUnavailable() {
  return (
    <section className="max-w-3xl mx-auto px-4 sm:px-6 py-20 text-center">
      <h1 className="text-3xl font-bold text-chalk-50">
        Daily card unavailable
      </h1>
      <p className="mt-3 text-chalk-300">
        Couldn&apos;t load <code>/data/mlb/mlb_daily.json</code>. The morning
        build may not have completed yet, or the data file isn&apos;t deployed
        with this build.
      </p>
    </section>
  );
}
