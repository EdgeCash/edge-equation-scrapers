/** @type {import('next').NextConfig} */
const nextConfig = {
  // Always serve fresh data files; Vercel CDN caches the page output but
  // mlb_daily.json should be re-pulled on every request so newly-pushed
  // daily builds appear immediately.
  reactStrictMode: true,
};

module.exports = nextConfig;
