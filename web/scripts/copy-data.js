#!/usr/bin/env node
/**
 * Copy the data pipeline's outputs into the Next.js public/ tree so they're
 * served at /data/mlb/* in the deployed site.
 *
 * The data files live at the repo root in /public/data/, generated daily by
 * the GitHub Actions cron. Next.js only serves what's inside its own
 * project root (`web/`), so we copy on each build. Side note: this also
 * means Vercel rebuilds (which happen on every commit to main, including
 * the daily data commit) automatically pick up fresh data — no manual
 * trigger needed.
 *
 * Run as a pre-step to `next dev` and `next build` (see package.json).
 * Safe to run when the source dir doesn't exist (just logs and exits 0).
 */

const fs = require("fs");
const path = require("path");

const SRC = path.join(__dirname, "..", "..", "public", "data");
const DEST = path.join(__dirname, "..", "public", "data");

if (!fs.existsSync(SRC)) {
  console.warn(`[copy-data] Source ${SRC} doesn't exist; skipping.`);
  process.exit(0);
}

// Wipe and re-copy so removed files in the source don't linger in dest.
fs.rmSync(DEST, { recursive: true, force: true });
fs.mkdirSync(path.dirname(DEST), { recursive: true });
fs.cpSync(SRC, DEST, { recursive: true });

const fileCount = countFiles(DEST);
console.log(`[copy-data] Copied ${fileCount} file(s) from ${SRC} → ${DEST}`);

function countFiles(dir) {
  let count = 0;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) count += countFiles(full);
    else count += 1;
  }
  return count;
}
