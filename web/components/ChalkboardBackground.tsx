/* Decorative SVG layer — math equations and grids drawn in soft chalk-blue.
 *
 * Sits absolutely behind hero / methodology / track-record sections to add
 * the "controlled chaos" texture. All equations have low opacity so they
 * never compete with the data tables that read on top.
 *
 * Equations chosen are real ones from the model:
 *   - NegBin parameter solve:  r = μ² / (σ² − μ)
 *   - Kelly:                   f* = (bp − q) / b
 *   - Brier:                   B = E[(p − y)²]
 *   - CLV:                     ΔP = 1/D_c − 1/D_o
 */

interface Props {
  /** Subtle (default) for content areas; full for the hero. */
  intensity?: "subtle" | "full";
  className?: string;
}

export function ChalkboardBackground({ intensity = "subtle", className = "" }: Props) {
  const opacity = intensity === "full" ? 0.18 : 0.08;
  return (
    <div
      aria-hidden
      className={`pointer-events-none absolute inset-0 overflow-hidden ${className}`}
      style={{ zIndex: 0 }}
    >
      {/* Top-left: NegBin solve */}
      <svg
        className="absolute -top-2 left-4 sm:left-12 select-none"
        width="320"
        height="80"
        viewBox="0 0 320 80"
        fill="none"
        style={{ opacity }}
      >
        <text
          x="0"
          y="48"
          fontFamily="ui-monospace, monospace"
          fontSize="36"
          fill="#cbd5e1"
        >
          r = μ² / (σ² − μ)
        </text>
      </svg>

      {/* Right: Kelly equation */}
      <svg
        className="absolute top-16 right-4 sm:right-16 select-none hidden sm:block"
        width="280"
        height="60"
        viewBox="0 0 280 60"
        fill="none"
        style={{ opacity }}
      >
        <text
          x="0"
          y="40"
          fontFamily="ui-monospace, monospace"
          fontSize="30"
          fill="#cbd5e1"
        >
          f* = (bp − q) / b
        </text>
      </svg>

      {/* Bottom-left: CLV */}
      <svg
        className="absolute bottom-8 left-4 sm:left-20 select-none hidden md:block"
        width="320"
        height="60"
        viewBox="0 0 320 60"
        fill="none"
        style={{ opacity }}
      >
        <text
          x="0"
          y="40"
          fontFamily="ui-monospace, monospace"
          fontSize="28"
          fill="#cbd5e1"
        >
          CLV = 1/D_close − 1/D_open
        </text>
      </svg>

      {/* Bottom-right: Brier */}
      <svg
        className="absolute bottom-12 right-8 select-none hidden md:block"
        width="240"
        height="60"
        viewBox="0 0 240 60"
        fill="none"
        style={{ opacity }}
      >
        <text
          x="0"
          y="40"
          fontFamily="ui-monospace, monospace"
          fontSize="28"
          fill="#cbd5e1"
        >
          B = E[(p − y)²]
        </text>
      </svg>

      {/* Eraser smudges — soft glowing ellipses */}
      <div
        className="absolute -top-10 -right-10 w-72 h-72 rounded-full blur-3xl"
        style={{
          background:
            "radial-gradient(circle, rgba(56,189,248,0.12), transparent 70%)",
        }}
      />
      <div
        className="absolute bottom-0 -left-10 w-80 h-80 rounded-full blur-3xl"
        style={{
          background:
            "radial-gradient(circle, rgba(255,255,255,0.05), transparent 70%)",
        }}
      />
    </div>
  );
}
