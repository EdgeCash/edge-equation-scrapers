import type { Config } from "tailwindcss";

// Edge Equation v5.0 brand palette.
//
// Visual direction: "controlled chaos" — mathematician's chalkboard in the
// middle of a loud sportsbook. Dark slate base, electric blue for tiers and
// CTAs, warm chalk-white for body text, hand-drawn imperfection accents.

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Chalkboard surfaces (deepest first)
        chalkboard: {
          950: "#070d16", // deepest (nav, footer)
          900: "#0a1421", // base background
          800: "#101b2c", // raised cards
          700: "#1a2738", // table rows / hover
          600: "#2a3a52", // borders
        },
        // Tier system — electric blue is the brand color
        elite:    "#38bdf8", // Signal Elite (sky-400) — brightest
        strong:   "#22c55e", // Strong Signal (deep green)
        moderate: "#f59e0b", // Moderate Signal (amber)
        lean:     "#94a3b8", // Lean Signal (slate-400)
        nosignal: "#ef4444", // No Signal (red-500)
        // Chalk text
        chalk: {
          50:  "#f8fafc",
          100: "#e2e8f0",
          300: "#94a3b8",
          500: "#64748b",
        },
      },
      fontFamily: {
        // Inter for body, Caveat for hand-drawn accents
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
        chalk: ["var(--font-caveat)", "cursive"],
        mono: ["ui-monospace", "SFMono-Regular", "monospace"],
      },
      backgroundImage: {
        // Soft grid + diagonal noise to evoke a real chalkboard surface
        "chalkboard-grid": `
          linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px),
          linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px)
        `,
        "chalk-smudge":
          "radial-gradient(ellipse at 30% 20%, rgba(56,189,248,0.08), transparent 50%), " +
          "radial-gradient(ellipse at 80% 70%, rgba(255,255,255,0.04), transparent 60%)",
      },
      backgroundSize: {
        "chalkboard-grid": "40px 40px",
      },
      boxShadow: {
        elite: "0 0 0 1px rgba(56,189,248,0.4), 0 4px 24px rgba(56,189,248,0.15)",
      },
    },
  },
  plugins: [],
};

export default config;
