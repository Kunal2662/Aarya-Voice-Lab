// Real-browser (headless Chromium) tests for FE-2.1's three new
// dashboard-visual-language primitives: avl-icon-badge, avl-stat-tile,
// avl-meter. The central concern across all of these is the same
// real-data-only discipline enforced everywhere else in this app:
// omitting a value must render an honest "Not available"/"Not
// measured" fallback, never a fabricated number or a silently blank
// tile.
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
    const page = await browser.newPage();
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

test("1. avl-icon-badge renders the requested icon inside a toned colored chip", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    const result = await page.evaluate(async () => {
      await import("/components/icon-badge.js");
      const el = document.createElement("avl-icon-badge");
      el.setAttribute("tone", "violet");
      el.setAttribute("icon", "batches");
      document.body.appendChild(el);
      await new Promise((r) => setTimeout(r, 20));
      const badge = el.shadowRoot.querySelector(".badge");
      const icon = badge.querySelector("avl-icon");
      return {
        hasBadge: !!badge,
        hasVioletClass: badge.classList.contains("violet"),
        iconName: icon.getAttribute("name"),
        bg: getComputedStyle(badge).backgroundColor,
      };
    });
    assert.equal(result.hasBadge, true);
    assert.equal(result.hasVioletClass, true);
    assert.equal(result.iconName, "batches");
    assert.notEqual(result.bg, "rgba(0, 0, 0, 0)", "the badge must have a real resolved background, not a transparent/unstyled one");
  });
});

test("2. avl-stat-tile with a value renders it, tabular-nums, plus its unit", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    const result = await page.evaluate(async () => {
      await import("/components/stat-tile.js");
      const el = document.createElement("avl-stat-tile");
      el.setAttribute("label", "Datasets");
      el.setAttribute("value", "4");
      el.setAttribute("unit", "Total");
      el.setAttribute("tone", "violet");
      el.setAttribute("icon", "batches");
      document.body.appendChild(el);
      await new Promise((r) => setTimeout(r, 20));
      const valueEl = el.shadowRoot.querySelector(".value");
      return {
        value: valueEl.textContent,
        unit: el.shadowRoot.querySelector(".unit").textContent,
        fontVariant: getComputedStyle(valueEl).fontVariantNumeric,
        hasUnavailable: !!el.shadowRoot.querySelector(".unavailable"),
      };
    });
    assert.equal(result.value, "4");
    assert.equal(result.unit, "Total");
    assert.match(result.fontVariant, /tabular-nums/);
    assert.equal(result.hasUnavailable, false);
  });
});

test("3. avl-stat-tile omitting value renders the honest 'Not available' fallback, never a fabricated 0", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    const result = await page.evaluate(async () => {
      await import("/components/stat-tile.js");
      const el = document.createElement("avl-stat-tile");
      el.setAttribute("label", "Recordings");
      el.setAttribute("tone", "blue");
      el.setAttribute("icon", "recordings");
      document.body.appendChild(el);
      await new Promise((r) => setTimeout(r, 20));
      return {
        unavailableText: el.shadowRoot.querySelector(".unavailable")?.textContent,
        hasValueRow: !!el.shadowRoot.querySelector(".value-row"),
      };
    });
    assert.equal(result.unavailableText, "Not available");
    assert.equal(result.hasValueRow, false, "no value row (and certainly no '0') should render when value is omitted");
  });
});

test("4. avl-stat-tile projects its default-slot detail text", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    const assigned = await page.evaluate(async () => {
      await import("/components/stat-tile.js");
      const el = document.createElement("avl-stat-tile");
      el.setAttribute("label", "Datasets");
      el.setAttribute("value", "4");
      el.textContent = "3 Ready · 1 Processing";
      document.body.appendChild(el);
      await new Promise((r) => setTimeout(r, 20));
      const slot = el.shadowRoot.querySelector(".detail slot");
      return slot.assignedNodes().map((n) => n.textContent);
    });
    assert.deepEqual(assigned, ["3 Ready · 1 Processing"]);
  });
});

test("5. avl-meter with real value/max renders a percentage and an accessible progressbar", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    const result = await page.evaluate(async () => {
      await import("/components/meter.js");
      const el = document.createElement("avl-meter");
      el.setAttribute("label", "Pipeline");
      el.setAttribute("value", "9");
      el.setAttribute("max", "24");
      el.setAttribute("tone", "teal");
      document.body.appendChild(el);
      await new Promise((r) => setTimeout(r, 20));
      const bar = el.shadowRoot.querySelector('[role="progressbar"]');
      return {
        percentText: el.shadowRoot.querySelector(".percent")?.textContent,
        valuenow: bar?.getAttribute("aria-valuenow"),
        valuemin: bar?.getAttribute("aria-valuemin"),
        valuemax: bar?.getAttribute("aria-valuemax"),
        fillWidth: el.shadowRoot.querySelector(".fill")?.style.width,
      };
    });
    assert.equal(result.percentText, "38%");
    assert.equal(result.valuenow, "38");
    assert.equal(result.valuemin, "0");
    assert.equal(result.valuemax, "100");
    assert.equal(result.fillWidth, `${(9 / 24) * 100}%`);
  });
});

test("6. avl-meter omitting value/max renders 'Not measured', never a fabricated 0% bar", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    const result = await page.evaluate(async () => {
      await import("/components/meter.js");
      const el = document.createElement("avl-meter");
      el.setAttribute("label", "CPU");
      el.setAttribute("tone", "pink");
      document.body.appendChild(el);
      await new Promise((r) => setTimeout(r, 20));
      return {
        unmeasuredText: el.shadowRoot.querySelector(".unmeasured")?.textContent,
        hasTrack: !!el.shadowRoot.querySelector(".track"),
        hasPercent: !!el.shadowRoot.querySelector(".percent"),
      };
    });
    assert.equal(result.unmeasuredText, "Not measured");
    assert.equal(result.hasTrack, false, "no progress bar track (which would visually imply a real 0% measurement) should render when unmeasured");
    assert.equal(result.hasPercent, false);
  });
});
