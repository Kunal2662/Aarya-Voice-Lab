// Real-browser (headless Chromium) tests for FE-1.6's visual identity
// pass: notice-banner.js's dismiss control now uses a real icon instead
// of a raw "✕" Unicode character (completing FE-1.3's own "no random
// Unicode symbols as final icons" principle for the one other spot it
// still applied to), and avl-metric-placeholder's values render with
// tabular-nums for column alignment. Both are small, token-only,
// non-interaction-changing refinements -- deliberately not a broad
// redesign, per FE-1.6's own "do not redesign working interaction
// models merely for aesthetics" instruction.
import { test } from "node:test";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { createStaticServer } from "../tools/serve.mjs";

const PLAYWRIGHT_INDEX = "/opt/node22/lib/node_modules/playwright/index.js";
const CHROMIUM_EXECUTABLE = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";

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

test("1. notice-banner's dismiss control renders a real icon, not a Unicode glyph, and keeps its accessible name", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    const result = await page.evaluate(async () => {
      const banner = document.createElement("avl-notice-banner");
      banner.setAttribute("tone", "info");
      banner.setAttribute("dismissible", "");
      banner.textContent = "Test notice";
      document.body.appendChild(banner);
      await new Promise((r) => setTimeout(r, 30));
      const close = banner.shadowRoot.querySelector(".close");
      const icon = close.querySelector("avl-icon");
      const svg = icon ? icon.shadowRoot.querySelector("svg") : null;
      return {
        ariaLabel: close.getAttribute("aria-label"),
        rawGlyphText: close.textContent.trim(),
        hasIcon: !!icon,
        iconIsHidden: svg ? svg.getAttribute("aria-hidden") : null,
      };
    });
    assert.equal(result.ariaLabel, "Dismiss notice");
    assert.equal(result.rawGlyphText, "", "no raw Unicode glyph text should remain as the button's content");
    assert.equal(result.hasIcon, true);
    assert.equal(result.iconIsHidden, "true", "the icon must stay decorative since aria-label already carries the accessible name");
  });
});

test("2. dismiss still works exactly as before: clicking it dispatches avl-dismiss and removes the banner", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    const result = await page.evaluate(async () => {
      const banner = document.createElement("avl-notice-banner");
      banner.setAttribute("tone", "warning");
      banner.setAttribute("dismissible", "");
      document.body.appendChild(banner);
      await new Promise((r) => setTimeout(r, 30));
      let fired = false;
      banner.addEventListener("avl-dismiss", () => {
        fired = true;
      });
      banner.shadowRoot.querySelector(".close").click();
      await new Promise((r) => setTimeout(r, 30));
      return { fired, stillInDom: document.body.contains(banner) };
    });
    assert.equal(result.fired, true);
    assert.equal(result.stillInDom, false);
  });
});

test("3. avl-metric-placeholder values render with tabular-nums for column alignment", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    const fontVariant = await page.evaluate(async () => {
      const metric = document.createElement("avl-metric-placeholder");
      metric.setAttribute("label", "Total stages");
      metric.setAttribute("value", "24");
      document.body.appendChild(metric);
      await new Promise((r) => setTimeout(r, 30));
      const valueEl = metric.shadowRoot.querySelector(".value");
      return getComputedStyle(valueEl).fontVariantNumeric;
    });
    assert.match(fontVariant, /tabular-nums/);
  });
});
