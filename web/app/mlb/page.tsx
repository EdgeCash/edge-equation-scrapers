// Drop this into your Next.js App Router site to mount the MLB dashboard
// at /mlb. Adjust the import paths to match where you copy the components.
import { MLBDashboard } from "../../components/MLBDashboard";

export const dynamic = "force-dynamic"; // always serve the latest data

export default function MLBPage() {
  return (
    <main className="max-w-7xl mx-auto p-6">
      <MLBDashboard />
    </main>
  );
}
