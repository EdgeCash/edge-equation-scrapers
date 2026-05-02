import Link from "next/link";
import { ChalkboardBackground } from "../components/ChalkboardBackground";
import { TierBadge } from "../components/TierBadge";

export const dynamic = "force-dynamic";

export default function HomePage() {
  return (
    <>
      <Hero />
      <TierExplainer />
      <Pillars />
      <CallToAction />
    </>
  );
}

/* ---------- Hero ---------- */

function Hero() {
  return (
    <section className="relative overflow-hidden">
      <ChalkboardBackground intensity="full" />
      <div className="relative z-10 max-w-7xl mx-auto px-4 sm:px-6 py-20 sm:py-28">
        <p className="font-chalk text-2xl text-elite/80 -rotate-1 inline-block">
          v5.0 · MLB
        </p>
        <h1 className="mt-2 text-4xl sm:text-6xl font-bold tracking-tight text-chalk-50 max-w-4xl">
          Facts. Not <span className="text-elite">Feelings</span>.
        </h1>
        <p className="mt-6 text-lg sm:text-xl text-chalk-300 max-w-2xl leading-relaxed">
          Transparent sports analytics. Honest modeling, rigorous testing,
          public learning. We track every pick against the closing line and
          publish the math behind it.
        </p>

        <div className="mt-10 flex flex-wrap gap-4">
          <Link href="/daily-card" className="btn-primary">
            Today&apos;s Card
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="m9 18 6-6-6-6" />
            </svg>
          </Link>
          <Link href="/methodology" className="btn-ghost">
            How the model works
          </Link>
        </div>

        {/* Process-over-picks strip */}
        <div className="mt-16 grid sm:grid-cols-3 gap-6 max-w-4xl">
          <ProcessChip
            stat="3–8"
            label="High-conviction plays per day"
            note="Some days zero. That's a feature."
          />
          <ProcessChip
            stat="200+"
            label="Bet samples before a market ships"
            note="Plus +1% ROI and Brier <0.246"
          />
          <ProcessChip
            stat="100%"
            label="CLV-tracked"
            note="Every pick snapped at close"
          />
        </div>
      </div>
    </section>
  );
}

function ProcessChip({
  stat,
  label,
  note,
}: {
  stat: string;
  label: string;
  note: string;
}) {
  return (
    <div className="chalk-card p-5">
      <p className="font-chalk text-4xl text-elite leading-none">{stat}</p>
      <p className="mt-3 text-sm font-medium text-chalk-100">{label}</p>
      <p className="mt-1 text-xs text-chalk-500">{note}</p>
    </div>
  );
}

/* ---------- Tier system explainer ---------- */

function TierExplainer() {
  const tiers: Array<{
    tier:
      | "Signal Elite"
      | "Strong Signal"
      | "Moderate Signal"
      | "Lean Signal"
      | "No Signal";
    edge: string;
    units: string;
    desc: string;
  }> = [
    {
      tier: "Signal Elite",
      edge: "≥ 4%",
      units: "2u+",
      desc: "Rare. The model has strong, well-calibrated edge against the close.",
    },
    {
      tier: "Strong Signal",
      edge: "3–4%",
      units: "1.5–2u",
      desc: "Real edge after vig and variance. Bread-and-butter plays.",
    },
    {
      tier: "Moderate Signal",
      edge: "2–3%",
      units: "1u",
      desc: "Edge is there, position size reflects it.",
    },
    {
      tier: "Lean Signal",
      edge: "1–2%",
      units: "0.5u",
      desc: "Informational. We're noting the lean but it's below the action threshold.",
    },
    {
      tier: "No Signal",
      edge: "< 1%",
      units: "Pass",
      desc: "Market is efficient or model is unsure. We don't bet.",
    },
  ];

  return (
    <section className="relative max-w-7xl mx-auto px-4 sm:px-6 py-16 sm:py-24">
      <div className="max-w-3xl">
        <h2 className="text-3xl sm:text-4xl font-bold text-chalk-50 chalk-underline">
          Conviction tiers
        </h2>
        <p className="mt-4 text-chalk-300 leading-relaxed">
          Every play is tagged with a tier and a Kelly unit count. Tier tells
          you <em>how confident the model is</em>. Units tell you{" "}
          <em>how much to bet</em>. The pairing is the whole point.
        </p>
      </div>

      <div className="mt-10 grid gap-4 sm:gap-3">
        {tiers.map((t) => (
          <div
            key={t.tier}
            className={
              t.tier === "Signal Elite" ? "chalk-card-elite p-5" : "chalk-card p-5"
            }
          >
            <div className="flex flex-col sm:flex-row sm:items-center gap-4">
              <div className="sm:w-48 shrink-0">
                <TierBadge tier={t.tier} size="lg" />
              </div>
              <div className="flex-1">
                <p className="text-sm text-chalk-100">
                  <span className="font-mono text-chalk-300 mr-3">{t.edge}</span>
                  <span className="font-mono text-chalk-300 mr-3">·</span>
                  <span className="font-mono text-chalk-300 mr-3">{t.units}</span>
                </p>
                <p className="mt-1 text-sm text-chalk-300 leading-relaxed">
                  {t.desc}
                </p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ---------- Pillars / process ---------- */

function Pillars() {
  return (
    <section className="relative bg-chalkboard-900/60 border-y border-chalkboard-600/30">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-16 sm:py-20 grid md:grid-cols-3 gap-8">
        <Pillar
          title="Process > Picks"
          body="Every market is gated by a rolling backtest: 200+ bets, ≥+1% ROI, Brier under 0.246. If it can't clear the math, it stays off the card. We remove markets just as readily as we add them."
        />
        <Pillar
          title="CLV-first"
          body="Long-run profitability tracks closing-line value, not W/L. We snapshot every pick at close and publish 30-day rolling CLV alongside hit rate and ROI. Beating the close is the actual edge."
        />
        <Pillar
          title="Radical transparency"
          body="Brier scores, ROI per market, model versions, calibration, and limitations are all public. We show our work — including the markets where we currently can't beat the book."
        />
      </div>
    </section>
  );
}

function Pillar({ title, body }: { title: string; body: string }) {
  return (
    <div>
      <p className="text-elite font-mono text-xs uppercase tracking-wider">
        Core value
      </p>
      <h3 className="mt-2 text-xl font-semibold text-chalk-50">{title}</h3>
      <p className="mt-2 text-sm text-chalk-300 leading-relaxed">{body}</p>
    </div>
  );
}

/* ---------- CTA ---------- */

function CallToAction() {
  return (
    <section className="relative max-w-4xl mx-auto px-4 sm:px-6 py-16 sm:py-24 text-center">
      <h2 className="text-3xl sm:text-4xl font-bold text-chalk-50">
        Today&apos;s plays. <span className="text-elite">Or none, if the math says pass.</span>
      </h2>
      <p className="mt-4 text-chalk-300 max-w-2xl mx-auto">
        New card published every morning by 11:00 AM ET. Each play priced and
        tier-graded against the live market.
      </p>
      <div className="mt-8 flex flex-wrap justify-center gap-4">
        <Link href="/daily-card" className="btn-primary">
          See today&apos;s card
        </Link>
        <Link href="/track-record" className="btn-ghost">
          See the track record
        </Link>
      </div>
    </section>
  );
}
