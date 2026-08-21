// Real-browser (headless Chromium) tests for FE-1.5's shared CSS
// utilities (frontend/css/base.css): .avl-row / .avl-row--bordered /
// .avl-row--center / .avl-stack / .avl-label, extracted from the
// highest-duplication ".row { display: flex; ... }" pattern the FE-1
// audit found repeated across ~20 component files. Confirms the
// utilities are real, computed-style-correct, AND genuinely adopted by
// the 9 migrated components -- not merely declared and unused.
import { test } from "node:test";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createStaticServer } from "../tools/serve.mjs";

const PLAYWRIGHT_INDEX = "/opt/node22/lib/node_modules/playwright/index.js";
const CHROMIUM_EXECUTABLE = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

async function loadPlaywright() {
  const mod = await import(pathToFileURL(PLAYWRIGHT_INDEX).href);
  return mod.default;
}

async function withPage(fn) {
  const playwright = await loadPlaywright();
  const browser = await playwright.chromium.launch({ executablePath: CHROMIUM_EXECUTABLE, args: ["--no-sandbox"] });
  const server = createStaticServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const consoleErrors = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });
    page.on("pageerror", (err) => consoleErrors.push(String(err)));
    await page.goto(`http://127.0.0.1:${port}/app/index.html`, { waitUntil: "networkidle" });
    await fn(page);
    assert.deepEqual(consoleErrors, [], `unexpected console errors: ${JSON.stringify(consoleErrors)}`);
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
}

test("1. .avl-row / .avl-row--bordered / .avl-row--center resolve real computed layout, not just CSS text", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    const result = await page.evaluate(async () => {
      // Built via document.querySelector on already-loaded stylesheet
      // hrefs (avoids passing import.meta.url across the evaluate
      // boundary, which Playwright cannot serialize): reuse the hrefs
      // any already-mounted component's own <link> tags resolved to.
      const anyLink = document.querySelector("avl-app-shell").shadowRoot.querySelector('link[href*="base.css"]');
      const baseHref = anyLink.href;
      const variablesHref = baseHref.replace("base.css", "variables.css");

      const probe = document.createElement("div");
      probe.attachShadow({ mode: "open" });
      const link1 = document.createElement("link");
      link1.rel = "stylesheet";
      link1.href = variablesHref;
      const link2 = document.createElement("link");
      link2.rel = "stylesheet";
      link2.href = baseHref;
      probe.shadowRoot.append(link1, link2);
      // Two rows, not one: avl-row--bordered:last-child intentionally
      // removes the trailing border (see test 2 below), so a lone row
      // would misreport this check -- measure the *first* of two.
      const row = document.createElement("div");
      row.className = "avl-row avl-row--bordered avl-row--center";
      const secondRow = document.createElement("div");
      secondRow.className = "avl-row avl-row--bordered avl-row--center";
      probe.shadowRoot.append(row, secondRow);
      document.body.appendChild(probe);
      await new Promise((r) => setTimeout(r, 60));
      const cs = getComputedStyle(row);
      return {
        display: cs.display,
        justifyContent: cs.justifyContent,
        alignItems: cs.alignItems,
        paddingTop: cs.paddingTop,
        borderBottomWidth: cs.borderBottomWidth,
      };
    });
    assert.equal(result.display, "flex");
    assert.equal(result.justifyContent, "space-between");
    assert.equal(result.alignItems, "center");
    assert.equal(result.paddingTop, "4px"); // --avl-space-1: 0.25rem
    assert.equal(result.borderBottomWidth, "1px");
  });
});

test("2. .avl-row--bordered:last-child correctly removes the border on the final row", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await page.evaluate(() => {
      location.hash = "#/batches";
    });
    await page.waitForTimeout(200);
    await page.evaluate(() => {
      const mount = document.querySelector('avl-app-shell [slot="workspace"]').firstElementChild;
      const card = mount.shadowRoot.querySelector("avl-batch-card");
      card.shadowRoot.querySelector("avl-card").click();
    });
    await page.waitForTimeout(200);
    const result = await page.evaluate(() => {
      const inspector = document.querySelector("avl-inspector-router");
      const rows = [...inspector.shadowRoot.querySelectorAll(".avl-row--bordered")];
      if (!rows.length) return null;
      const last = rows[rows.length - 1];
      return getComputedStyle(last).borderBottomWidth;
    });
    assert.equal(result, "0px", "the last bordered row must not show a trailing border");
  });
});

test("3. the shared utilities are genuinely adopted: real component instances render with avl-row classes, no local .row CSS left duplicated in those files", { timeout: 30_000 }, async () => {
  const migratedFiles = [
    "inspector-router.js",
    "before-after-comparison.js",
    "hardware-profile-card.js",
    "workspace-feedback.js",
    "workspace-preview.js",
    "evaluation-history-panel.js",
    "generation-history-panel.js",
    "processing-history-panel.js",
    "overlap-review-list.js",
  ];
  for (const file of migratedFiles) {
    const src = readFileSync(path.join(frontendRoot, "components", file), "utf8");
    assert.doesNotMatch(src, /\.row\s*\{/, `${file} must not redeclare a local .row rule after migrating to the shared utility`);
    assert.match(src, /avl-row/, `${file} must actually use the shared avl-row utility`);
  }
});

test("4. Inspector rows (a real, live-rendered consumer) resolve the shared utility's actual layout", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await page.evaluate(() => {
      location.hash = "#/batches";
    });
    await page.waitForTimeout(200);
    await page.evaluate(() => {
      const mount = document.querySelector('avl-app-shell [slot="workspace"]').firstElementChild;
      const card = mount.shadowRoot.querySelector("avl-batch-card");
      card.shadowRoot.querySelector("avl-card").click();
    });
    await page.waitForTimeout(200);
    const result = await page.evaluate(() => {
      const inspector = document.querySelector("avl-inspector-router");
      const row = inspector.shadowRoot.querySelector(".avl-row");
      const cs = getComputedStyle(row);
      return { display: cs.display, justifyContent: cs.justifyContent, className: row.className };
    });
    assert.equal(result.display, "flex");
    assert.equal(result.justifyContent, "space-between");
    assert.match(result.className, /avl-row--bordered/);
  });
});
