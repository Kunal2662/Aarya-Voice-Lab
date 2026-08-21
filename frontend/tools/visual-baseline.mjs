#!/usr/bin/env node
// FE-1.7 -- visual regression baseline CLI. Zero dependencies (like
// every other tool in this project): uses the Playwright/Chromium
// already installed in this environment, Node's built-in fs/crypto,
// and an exact byte-for-byte PNG comparison (no image-diff package) --
// see tests/visual-scenarios.mjs's own header comment for why that's a
// valid, deterministic strategy here.
//
// Usage:
//   node tools/visual-baseline.mjs                 # compare against committed baselines, exit 1 on any diff
//   node tools/visual-baseline.mjs --update         # (re)write the committed baselines from the current app
//   node tools/visual-baseline.mjs --update NAME    # update just one scenario by name (e.g. "01-command-center")
//
// Baselines live in tests/visual-baselines/*.png and ARE committed to
// the repo (unlike the gitignored frontend/contracts/live/ pattern --
// these are meant to be reviewed and intentionally updated in a diff,
// not regenerated silently every run).
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { pathToFileURL } from "node:url";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createStaticServer } from "./serve.mjs";
import { SCENARIOS, VIEWPORT_NORMAL, applyScenario } from "../tests/visual-scenarios.mjs";

const PLAYWRIGHT_INDEX = "/opt/node22/lib/node_modules/playwright/index.js";
const CHROMIUM_EXECUTABLE = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
// Headless Chromium's default rasterizer introduces sub-pixel
// anti-aliasing/compositing jitter between otherwise-identical
// captures (confirmed: DOM text content byte-identical across two
// consecutive captures of the same scenario, yet the PNG bytes
// differed) -- these flags force a fully deterministic software
// rendering path so the exact byte-for-byte comparison this harness
// relies on is actually stable.
const CHROMIUM_DETERMINISTIC_ARGS = [
  "--no-sandbox",
  "--force-color-profile=srgb",
  "--disable-lcd-text",
  "--disable-partial-raster",
  "--disable-skia-runtime-opts",
  "--run-all-compositor-stages-before-draw",
  "--disable-gpu",
  "--font-render-hinting=none",
];
const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const baselineDir = path.join(frontendRoot, "tests", "visual-baselines");

async function loadPlaywright() {
  const mod = await import(pathToFileURL(PLAYWRIGHT_INDEX).href);
  return mod.default;
}

async function captureScenario(browser, baseUrl, scenario) {
  const page = await browser.newPage({ viewport: scenario.viewport || VIEWPORT_NORMAL });
  // Activates the app's own global prefers-reduced-motion contract
  // before any content loads -- see visual-scenarios.mjs for why this
  // is what makes the capture deterministic.
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(`${baseUrl}/app/index.html`, { waitUntil: "networkidle" });
  await applyScenario(page, scenario);
  const buffer = await page.screenshot();
  await page.close();
  return buffer;
}

async function main() {
  const args = process.argv.slice(2);
  const update = args.includes("--update");
  const onlyName = args.find((a) => !a.startsWith("--"));

  const playwright = await loadPlaywright();
  const browser = await playwright.chromium.launch({ executablePath: CHROMIUM_EXECUTABLE, args: CHROMIUM_DETERMINISTIC_ARGS });
  const server = createStaticServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  const baseUrl = `http://127.0.0.1:${port}`;

  if (update) mkdirSync(baselineDir, { recursive: true });

  const scenarios = onlyName ? SCENARIOS.filter((s) => s.name === onlyName) : SCENARIOS;
  if (onlyName && scenarios.length === 0) {
    console.error(`No scenario named "${onlyName}". Known scenarios: ${SCENARIOS.map((s) => s.name).join(", ")}`);
    process.exitCode = 1;
  }

  let failures = 0;
  try {
    for (const scenario of scenarios) {
      const buffer = await captureScenario(browser, baseUrl, scenario);
      const baselinePath = path.join(baselineDir, `${scenario.name}.png`);

      if (update) {
        writeFileSync(baselinePath, buffer);
        console.log(`[WROTE]   ${scenario.name}`);
        continue;
      }

      if (!existsSync(baselinePath)) {
        console.log(`[MISSING] ${scenario.name} -- no baseline yet, run with --update to create it`);
        failures += 1;
        continue;
      }
      const baseline = readFileSync(baselinePath);
      if (Buffer.compare(baseline, buffer) === 0) {
        console.log(`[MATCH]   ${scenario.name}`);
      } else {
        console.log(`[DIFF]    ${scenario.name} -- rendering changed; run with --update ${scenario.name} once the change is verified intentional`);
        failures += 1;
      }
    }
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }

  if (!update) {
    console.log(`\n${scenarios.length - failures}/${scenarios.length} scenarios matched their baseline.`);
    if (failures > 0) process.exitCode = 1;
  }
}

main();
