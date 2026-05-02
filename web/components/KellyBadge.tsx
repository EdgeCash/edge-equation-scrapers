import { KellyAdvice } from "../types";

const TIER_STYLES: Record<KellyAdvice, string> = {
  PASS: "bg-zinc-200 text-zinc-700",
  "0.5u": "bg-blue-100 text-blue-800",
  "1u": "bg-emerald-100 text-emerald-800",
  "2u": "bg-emerald-200 text-emerald-900 font-semibold",
  "3u": "bg-amber-200 text-amber-900 font-bold",
};

export function KellyBadge({ advice }: { advice: KellyAdvice | string | null | undefined }) {
  if (!advice) return null;
  const cls = TIER_STYLES[advice as KellyAdvice] ?? "bg-zinc-100 text-zinc-700";
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs ${cls}`}>
      {advice}
    </span>
  );
}
