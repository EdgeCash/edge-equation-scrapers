import Link from "next/link";

export function Footer() {
  return (
    <footer className="relative z-10 mt-16 border-t border-chalkboard-600/40 bg-chalkboard-950/60">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-10 grid gap-8 md:grid-cols-3">
        <div>
          <p className="text-chalk-50 font-semibold tracking-wide">
            Edge<span className="text-elite">Equation</span>
          </p>
          <p className="mt-2 text-sm text-chalk-300 italic">
            Facts. Not Feelings.
          </p>
          <p className="mt-3 text-xs text-chalk-500 leading-relaxed">
            Transparent sports analytics. Honest modeling. Public track record.
            Some days the right play is no play.
          </p>
        </div>

        <div className="text-sm">
          <p className="text-chalk-100 font-medium mb-3">Pages</p>
          <ul className="space-y-2 text-chalk-300">
            <li>
              <Link href="/daily-card" className="hover:text-elite">
                Daily Card
              </Link>
            </li>
            <li>
              <Link href="/track-record" className="hover:text-elite">
                Track Record
              </Link>
            </li>
            <li>
              <Link href="/methodology" className="hover:text-elite">
                Methodology
              </Link>
            </li>
          </ul>
        </div>

        <div className="text-xs text-chalk-500 leading-relaxed">
          <p className="text-chalk-100 font-medium mb-2 text-sm">Bet Responsibly</p>
          <p>
            Edge Equation is sports analytics, not financial or gambling advice.
            Past performance does not guarantee future results. Models can and
            will be wrong. Never wager more than you can afford to lose.
          </p>
          <p className="mt-3">
            US:{" "}
            <a
              href="https://www.ncpgambling.org/help-treatment/national-helpline-1-800-522-4700/"
              target="_blank"
              rel="noopener noreferrer"
              className="text-chalk-300 hover:text-elite underline"
            >
              National Helpline 1-800-522-4700
            </a>
          </p>
        </div>
      </div>

      <div className="border-t border-chalkboard-700/60 py-4 text-center text-xs text-chalk-500">
        © {new Date().getFullYear()} Edge Equation · v5.0
      </div>
    </footer>
  );
}
