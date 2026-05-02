import { ChalkboardBackground } from "../../components/ChalkboardBackground";

export const dynamic = "force-static";

export default function MethodologyPage() {
  return (
    <>
      <section className="relative overflow-hidden border-b border-chalkboard-600/40">
        <ChalkboardBackground />
        <div className="relative z-10 max-w-4xl mx-auto px-4 sm:px-6 py-12 sm:py-16">
          <p className="font-chalk text-2xl text-elite/80 -rotate-1 inline-block">
            How the model works
          </p>
          <h1 className="mt-1 text-4xl sm:text-5xl font-bold text-chalk-50">
            Methodology
          </h1>
          <p className="mt-6 text-chalk-300 max-w-2xl">
            We&apos;d rather show our work than make claims. Here&apos;s exactly
            what goes into a play and what we measure ourselves against.
          </p>
        </div>
      </section>

      <article className="max-w-4xl mx-auto px-4 sm:px-6 py-12 prose prose-invert prose-headings:text-chalk-50 prose-p:text-chalk-300 prose-strong:text-chalk-100 prose-a:text-elite prose-code:text-elite prose-code:bg-chalkboard-800 prose-code:px-1 prose-code:py-0.5 prose-code:rounded">
        <Section title="Projection model">
          <p>
            For each game we project per-team run scoring as a weighted blend
            of three signals:
          </p>
          <ul>
            <li>
              <strong>Season pace (45%)</strong> — full-season runs scored /
              allowed per game.
            </li>
            <li>
              <strong>Recent form (30%)</strong> — same metrics over the last
              ten games.
            </li>
            <li>
              <strong>Opponent context (25%)</strong> — opposing team&apos;s
              corresponding allowed / scored rate.
            </li>
          </ul>
          <p>
            Team aggregates use Bayesian shrinkage with k=15 ghost games of
            league average baseline so early-season noise can&apos;t produce a
            7-RPG team after a hot week.
          </p>
        </Section>

        <Section title="Adjustments stacked on top">
          <ul>
            <li>
              <strong>Starting pitcher</strong> — quality factor from FIP with a
              50-IP shrinkage prior. Applied 5/9 of full-game runs and 90% of
              first-5-innings projections.
            </li>
            <li>
              <strong>Bullpen</strong> — relief-only ERA per team, 150-IP prior.
              Carries the remaining 4/9 of full-game runs.
            </li>
            <li>
              <strong>Park factor</strong> — multi-year per-venue multiplier
              (Coors 1.18, Petco 0.92, etc).
            </li>
            <li>
              <strong>Weather</strong> — outdoor games get a temperature-based
              factor pulled from Open-Meteo at game time.
            </li>
          </ul>
        </Section>

        <Section title="Probability + Kelly sizing">
          <p>
            Run totals are modeled as a <strong>Negative Binomial</strong>{" "}
            distribution parameterized by the empirical season variance, not
            Poisson — MLB run totals are over-dispersed and Poisson would inflate
            tail probabilities. Win probabilities use a logistic on projected
            margin, with the slope <em>fitted from backtest residuals</em> each
            run rather than hardcoded.
          </p>
          <p>
            Bet sizing is <strong>half-Kelly</strong> capped at 5% of bankroll
            per play. When multiple correlated bets land on the same game, the
            sum is capped at 6% (full-Kelly across correlated bets over-stakes
            the slate).
          </p>
        </Section>

        <Section title="Market gating (the hard rule)">
          <p>
            A market is included on the daily card{" "}
            <strong>only if</strong> its rolling 200+ bet backtest shows{" "}
            <strong>≥+1% ROI</strong> AND <strong>Brier &lt; 0.246</strong>.
            Markets that fail still appear in their dedicated tabs (transparency)
            but stay off the headline card.
          </p>
          <p>
            Markets are re-evaluated weekly. <strong>Removing a market is a
            normal part of the process.</strong> We&apos;d rather publish nothing
            than publish marginal volume.
          </p>
        </Section>

        <Section title="What we track on ourselves">
          <ul>
            <li>
              <strong>ROI per market</strong> — flat 1u at -110 across the season
              backtest.
            </li>
            <li>
              <strong>Brier score</strong> — calibration check independent of
              W/L luck. Lower is better; 0.25 = pure noise.
            </li>
            <li>
              <strong>CLV</strong> — closing line value. The single best
              predictor of long-run profitability. Snapped near first pitch,
              published per pick on the track record.
            </li>
          </ul>
        </Section>

        <Section title="What we don't do">
          <ul>
            <li>Guarantee wins.</li>
            <li>Hide losing streaks.</li>
            <li>Publish marginal plays for content&apos;s sake.</li>
            <li>Charge before we can prove edge.</li>
          </ul>
        </Section>

        <Section title="Bet responsibly">
          <p className="text-sm text-chalk-500">
            This site is sports analytics, not financial or gambling advice.
            Past performance does not guarantee future results. Models can and
            will be wrong. Never wager more than you can afford to lose. US
            problem-gambling helpline:{" "}
            <a
              href="https://www.ncpgambling.org/help-treatment/national-helpline-1-800-522-4700/"
              target="_blank"
              rel="noopener noreferrer"
            >
              1-800-522-4700
            </a>
            .
          </p>
        </Section>
      </article>
    </>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-10 first:mt-0">
      <h2 className="chalk-underline">{title}</h2>
      {children}
    </section>
  );
}
