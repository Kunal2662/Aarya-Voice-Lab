// Real-browser (headless Chromium) tests for FE-1.3's <avl-icon>
// catalogue: every named icon renders real SVG (not a Unicode glyph),
// decorative icons are aria-hidden by default, an icon with a `label`
// exposes role="img"/aria-label instead, an unknown name renders
// visibly-unrecognised rather than a silent blank, and the sidebar
// actually uses this component now instead of a text glyph.
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

const ALL_DESTINATION_ICON_NAMES = [
  "command-center", "import", "batches", "recordings", "review", "processing", "preview",
  "feedback", "pipeline", "voices", "models", "calibration", "claude", "activity", "settings",
];

test("1. every sidebar destination's icon name resolves to a real SVG, not a Unicode glyph", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    const result = await page.evaluate(async (names) => {
      const { ICON_NAMES } = await import("/components/icon.js");
      return names.every((n) => ICON_NAMES.includes(n));
    }, ALL_DESTINATION_ICON_NAMES);
    assert.equal(result, true, "the icon catalogue must cover every one of the 15 routed destinations");
  });
});

test("2. the sidebar renders real <svg> icons, no Unicode glyph fallback character", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    const info = await page.evaluate(() => {
      const nav = document.querySelector("avl-sidebar-nav");
      const items = [...nav.shadowRoot.querySelectorAll(".item")];
      return items.map((item) => {
        const iconEl = item.querySelector(".icon avl-icon");
        const svg = iconEl ? iconEl.shadowRoot.querySelector("svg") : null;
        return { hasIconEl: !!iconEl, hasSvg: !!svg };
      });
    });
    assert.equal(info.length, 15, "all 15 routed destinations must have a sidebar item");
    for (const row of info) {
      assert.equal(row.hasIconEl, true);
      assert.equal(row.hasSvg, true);
    }
  });
});

test("3. a decorative icon (no label) is aria-hidden", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    const hidden = await page.evaluate(async () => {
      await import("/components/icon.js");
      const el = document.createElement("avl-icon");
      el.setAttribute("name", "settings");
      document.body.appendChild(el);
      await new Promise((r) => setTimeout(r, 20));
      return el.shadowRoot.querySelector("svg").getAttribute("aria-hidden");
    });
    assert.equal(hidden, "true");
  });
});

test("4. an icon with a label exposes role=img and aria-label instead of aria-hidden", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    const attrs = await page.evaluate(async () => {
      await import("/components/icon.js");
      const el = document.createElement("avl-icon");
      el.setAttribute("name", "settings");
      el.setAttribute("label", "Settings");
      document.body.appendChild(el);
      await new Promise((r) => setTimeout(r, 20));
      const svg = el.shadowRoot.querySelector("svg");
      return { role: svg.getAttribute("role"), label: svg.getAttribute("aria-label"), hidden: svg.getAttribute("aria-hidden") };
    });
    assert.equal(attrs.role, "img");
    assert.equal(attrs.label, "Settings");
    assert.equal(attrs.hidden, null);
  });
});

test("5. an unknown icon name renders visibly unrecognised, never a silent blank", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    const text = await page.evaluate(async () => {
      await import("/components/icon.js");
      const el = document.createElement("avl-icon");
      el.setAttribute("name", "not-a-real-icon");
      document.body.appendChild(el);
      await new Promise((r) => setTimeout(r, 20));
      return el.shadowRoot.textContent;
    });
    assert.match(text, /\?/, "an unknown icon name must render a visible marker, not nothing");
  });
});

test("6. icon color tracks the sidebar item's existing color rules via currentColor (no new color token)", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    const colorsMatch = await page.evaluate(() => {
      const nav = document.querySelector("avl-sidebar-nav");
      const activeItem = nav.shadowRoot.querySelector('.item[aria-current="page"]');
      const svg = activeItem.querySelector(".icon avl-icon").shadowRoot.querySelector("svg");
      const itemColor = getComputedStyle(activeItem).color;
      const svgColor = getComputedStyle(svg).color;
      return itemColor === svgColor;
    });
    assert.equal(colorsMatch, true, "the icon must inherit the active item's color, not a hardcoded one");
  });
});
