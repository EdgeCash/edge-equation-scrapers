/* Conviction tier badge per BRAND_GUIDE v0.2.
 *
 * Maps the model's edge_pct + Kelly fraction to one of five visual tiers.
 * Electric blue is reserved for Signal Elite — the rarest, highest-edge tier.
 *
 *   Signal Elite     ≥4% edge,  typically 2u+      (electric blue, glow)
 *   Strong Signal    3–4% edge, typically 1.5–2u   (deep green)
 *   Moderate Signal  2–3% edge, typically 1u       (amber)
 *   Lean Signal      1–2% edge, 0.5u (info only)   (slate)
 *   No Signal        <1% edge or PASS              (red)
 */

import type { CSSProperties } from "react";

export type ConvictionTier =
  | "Signal Elite"
  | "Strong Signal"
  | "Moderate Signal"
  | "Lean Signal"
  | "No Signal";

interface TierStyle {
  className: string;
  dotColor: string;
  hint: string;
}

const TIER_STYLES: Record<ConvictionTier, TierStyle> = {
  "Signal Elite": {
    className:
      "bg-elite/15 text-elite border border-elite/40 " +
      "shadow-[0_0_18px_rgba(56,189,248,0.35)] font-bold tracking-wide",
    dotColor: "#38bdf8",
    hint: "≥4% edge · 2u+",
  },
  "Strong Signal": {
    className: "bg-strong/15 text-strong border border-strong/40 font-semibold",
    dotColor: "#22c55e",
    hint: "3–4% edge · 1.5–2u",
  },
  "Moderate Signal": {
    className: "bg-moderate/15 text-moderate border border-moderate/40 font-semibold",
    dotColor: "#f59e0b",
    hint: "2–3% edge · 1u",
  },
  "Lean Signal": {
    className: "bg-lean/15 text-lean border border-lean/40",
    dotColor: "#94a3b8",
    hint: "1–2% edge · 0.5u (informational)",
  },
  "No Signal": {
    className: "bg-nosignal/10 text-nosignal/80 border border-nosignal/30",
    dotColor: "#ef4444",
    hint: "Pass — no edge or market efficient",
  },
};

/**
 * Translate an edge_pct (and optional Kelly fraction) into the brand tier.
 *
 * Per BRAND_GUIDE: tier is primarily edge-driven, with Kelly fraction as a
 * secondary check (a 4% edge at small Kelly% is still Signal Elite — the
 * Kelly is just smaller because the price was bigger).
 */
export function tierFromEdge(
  edgePct: number | null | undefined,
  kellyPct?: number | null,
): ConvictionTier {
  if (edgePct === null || edgePct === undefined) return "No Signal";
  if (edgePct >= 4) return "Signal Elite";
  if (edgePct >= 3) return "Strong Signal";
  if (edgePct >= 2) return "Moderate Signal";
  if (edgePct >= 1) return "Lean Signal";
  return "No Signal";
}

interface Props {
  tier: ConvictionTier;
  size?: "sm" | "md" | "lg";
  showHint?: boolean;
  className?: string;
}

export function TierBadge({ tier, size = "md", showHint = false, className = "" }: Props) {
  const style = TIER_STYLES[tier];
  const sizeCls = {
    sm: "text-[10px] px-2 py-0.5",
    md: "text-xs px-2.5 py-1",
    lg: "text-sm px-3.5 py-1.5",
  }[size];

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md uppercase ${style.className} ${sizeCls} ${className}`}
      title={showHint ? undefined : style.hint}
    >
      <span
        aria-hidden
        className="h-1.5 w-1.5 rounded-full"
        style={{ backgroundColor: style.dotColor } as CSSProperties}
      />
      <span className="whitespace-nowrap">{tier}</span>
      {showHint && (
        <span className="hidden sm:inline text-[10px] opacity-70 normal-case ml-1">
          {style.hint}
        </span>
      )}
    </span>
  );
}

/** Convenience: render directly from raw edge_pct without the caller mapping. */
export function TierBadgeFromEdge({
  edgePct,
  kellyPct,
  ...props
}: { edgePct: number | null | undefined; kellyPct?: number | null } & Omit<Props, "tier">) {
  return <TierBadge tier={tierFromEdge(edgePct, kellyPct)} {...props} />;
}
