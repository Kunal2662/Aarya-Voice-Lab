// FE-1.7 -- visual regression suite. Runs as part of the normal
// `node --test tests/*.test.mjs` run, capturing each scenario from
// tests/visual-scenarios.mjs in a real headless-Chromium page and
// comparing it byte-for-byte against the committed baseline PNGs in
// tests/visual-baselines/. See visual-scenarios.mjs's header comment
// for why exact byte comparison (no fuzzy image-diff) is valid here,
// and tools/visual-baseline.mjs for the CLI that generates/updates
// these baselines -- both share the same scenario list and the same
// deterministic Chromium launch flags so what a baseline was captured
// from can never drift from what this test compares against.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { pathToFileURL, fileURLToPath } from "node:url";
import path from "node:path";
import { createStaticServer } from "../tools/serve.mjs";
import { SCENARIOS, VIEWPORT_NORMAL, applyScenario } from "./visual-scenarios.mjs";

const PLAYWRIGHT_INDEX = "/opt/node22/lib/node_modules/playwright/index.js";
const CHROMIUM_EXECUTABLE = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
// Kept identical to tools/visual-baseline.mjs's CHROMIUM_DETERMINISTIC_ARGS
// -- see that file's comment for why these flags are required.
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

const testsDir = path.dirname(fileURLToPath(import.meta.url));
const baselineDir = path.join(testsDir, "visual-baselines");

async function loadPlaywright() {
  const mod = await import(pathToFileURL(PLAYWRIGHT_INDEX).href);
  return mod.default;
}

test("visual regression: all scenarios match their committed baseline", { timeout: 120_000 }, async () => {
  const playwright = await loadPlaywright();
  const browser = await playwright.chromium.launch({ executablePath: CHROMIUM_EXECUTABLE, args: CHROMIUM_DETERMINISTIC_ARGS });
  const server = createStaticServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  const baseUrl = `http://127.0.0.1:${port}`;

  const mismatches = [];
  try {
    for (const scenario of SCENARIOS) {
      const baselinePath = path.join(baselineDir, `${scenario.name}.png`);
      if (!existsSync(baselinePath)) {
        mismatches.push(`${scenario.name}: no baseline committed (run tools/visual-baseline.mjs --update ${scenario.name})`);
        continue;
      }

      const page = await browser.newPage({ viewport: scenario.viewport || VIEWPORT_NORMAL });
      await page.emulateMedia({ reducedMotion: "reduce" });
      await page.goto(`${baseUrl}/app/index.html`, { waitUntil: "networkidle" });
      await applyScenario(page, scenario);
      const buffer = await page.screenshot();
      await page.close();

      const baseline = readFileSync(baselinePath);
      if (Buffer.compare(baseline, buffer) !== 0) {
        mismatches.push(`${scenario.name}: rendering differs from committed baseline`);
      }
    }
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }

  assert.deepEqual(mismatches, [], `visual regression mismatches:\n${mismatches.join("\n")}`);
});
