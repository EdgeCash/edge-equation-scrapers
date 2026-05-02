import type { Metadata } from "next";
import { Inter, Caveat } from "next/font/google";
import { Navigation } from "../components/Navigation";
import { Footer } from "../components/Footer";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const caveat = Caveat({
  subsets: ["latin"],
  variable: "--font-caveat",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Edge Equation — Facts. Not Feelings.",
  description:
    "Transparent, high-signal sports analytics. Honest modeling, rigorous testing, and public learning. We track Brier, ROI, and CLV — and we publish empty cards when the math says pass.",
  openGraph: {
    title: "Edge Equation — Facts. Not Feelings.",
    description:
      "Transparent, high-signal sports analytics. Honest modeling, rigorous testing, and public learning.",
    type: "website",
  },
  themeColor: "#0a1421",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${caveat.variable}`}>
      <body className="font-sans">
        <div className="relative min-h-screen flex flex-col">
          <Navigation />
          <main className="flex-1 relative">{children}</main>
          <Footer />
        </div>
      </body>
    </html>
  );
}
