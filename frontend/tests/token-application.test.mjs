// Real-browser (headless Chromium) tests proving design tokens actually
// apply as COMPUTED STYLES, not merely that CSS text contains
// "--token-name". Written after discovering and fixing a pre-existing,
// codebase-wide defect (predating FE-1, confirmed via `git stash`
// against the pristine 0bd6385 HEAD): every token was declared under
// :root in frontend/tools/build-css-variables.mjs's generated
// variables.css, but every component only ever links that file into
// its OWN Shadow DOM (base-element.js's _linkSharedStyles()) -- and
// :root never matches anything inside a shadow tree (only :host does),
// so the tokens were silently inert everywhere, in every real browser,
// since VL-D0. Confirmed with a minimal, codebase-independent isolated
// test: `:root{--x:red}` inside a shadow <style> left computed color at
// the browser's initial black; `:host{--y:blue}` correctly applied.
//
// The fix (frontend/tools/build-css-variables.mjs, app/index.html,
// shell/index.html):
//   - Typography/spacing/radius/layout/motion tokens have no theme
//     reactivity to preserve, so their generated blocks now target
//     `:host, :root` -- safe and sufficient via the existing
//     _linkSharedStyles() per-component link alone.
//   - Color tokens are reactive to an ancestor attribute
//     (`<html data-theme="dark">`, set by avl-theme-toggle.js) that no
//     :host selector can ever observe (a shadow tree cannot react to an
//     attribute on an element outside itself). Redeclaring color via
//     :host would also be actively wrong: a value set directly on an
//     element via :host always wins the cascade over an inherited one,
//     which would permanently pin every component to one theme
//     regardless of runtime toggling. So the color block stays
//     :root-scoped, unchanged, and app/index.html + shell/index.html
//     now also link variables.css/base.css at the real document root --
//     giving those exact :root/[data-theme] rules a genuine <html> to
//     match, with the resulting values inheriting into every shadow
//     tree automatically via normal CSS custom-property inheritance
//     (which, uniquely among CSS properties, crosses shadow boundaries).
//
// These tests assert actual getComputedStyle() results against the
// real hex/px/ms values in frontend/tokens/*.json -- not CSS text
// content -- across multiple components from multiple workspaces, and
// across both the light default and the explicit dark-theme toggle.
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

const color = JSON.parse(readFileSync(path.join(frontendRoot, "tokens", "color.json"), "utf8"));

function hexToRgb(hex) {
  const n = parseInt(hex.replace("#", ""), 16);
  return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
}

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

// 1. COLOR — avl-button's primary variant, a fresh standalone instance.
test("1. color: avl-button primary background/foreground resolve to real light-theme token hex", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    const result = await page.evaluate(async () => {
      const btn = document.createElement("avl-button");
      btn.setAttribute("variant", "primary");
      btn.textContent = "Test";
      document.body.appendChild(btn);
      await new Promise((r) => setTimeout(r, 30));
      const cs = getComputedStyle(btn.shadowRoot.querySelector("button"));
      return { background: cs.backgroundColor, color: cs.color };
    });
    assert.equal(result.background, hexToRgb(color.themes.light.brand.accent));
    assert.equal(result.color, hexToRgb(color.themes.light.text.inverse));
  });
});

// 2. COLOR reactivity — the explicit theme toggle (an <html data-theme>
// change on a totally different, non-shadow element) must still change
// what a shadow-DOM button's colors compute to, proving delivery is via
// real inheritance from the document root, not a locally pinned value.
test("2. color: toggling to dark theme changes a live button's computed colors to the dark-theme token values", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    const before = await page.evaluate(async () => {
      const btn = document.createElement("avl-button");
      btn.setAttribute("variant", "primary");
      btn.id = "probe";
      document.body.appendChild(btn);
      await new Promise((r) => setTimeout(r, 30));
      return getComputedStyle(btn.shadowRoot.querySelector("button")).backgroundColor;
    });
    assert.equal(before, hexToRgb(color.themes.light.brand.accent));

    const after = await page.evaluate(async () => {
      const toggle = document.querySelector("avl-theme-toggle");
      toggle.shadowRoot.querySelector("button").click(); // system -> light
      await new Promise((r) => setTimeout(r, 30));
      toggle.shadowRoot.querySelector("button").click(); // light -> dark
      // avl-button has a 100ms background transition (--avl-duration-fast);
      // wait past it so this measures the settled color, not a
      // mid-transition interpolated one.
      await new Promise((r) => setTimeout(r, 200));
      const btn = document.getElementById("probe");
      return {
        themeAttr: document.documentElement.getAttribute("data-theme"),
        background: getComputedStyle(btn.shadowRoot.querySelector("button")).backgroundColor,
      };
    });
    assert.equal(after.themeAttr, "dark");
    assert.equal(after.background, hexToRgb(color.themes.dark.brand.accent));
    assert.notEqual(after.background, before, "dark-theme background must differ from the light-theme one");
  });
});

// 3. SPACING — avl-button's padding.
test("3. spacing: avl-button padding resolves to the real --avl-space-4 pixel value", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    const paddingLeft = await page.evaluate(async () => {
      const btn = document.createElement("avl-button");
      btn.textContent = "Test";
      document.body.appendChild(btn);
      await new Promise((r) => setTimeout(r, 30));
      return getComputedStyle(btn.shadowRoot.querySelector("button")).paddingLeft;
    });
    assert.equal(paddingLeft, "16px"); // --avl-space-4: 1rem
  });
});

// 4. BORDER RADIUS — avl-button (md) and avl-status-badge (pill).
test("4. border radius: avl-button and avl-status-badge resolve to their real radius token pixel values", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    const result = await page.evaluate(async () => {
      const btn = document.createElement("avl-button");
      btn.textContent = "Test";
      document.body.appendChild(btn);
      const badge = document.createElement("avl-status-badge");
      badge.setAttribute("domain", "core");
      badge.setAttribute("state", "ready");
      document.body.appendChild(badge);
      await new Promise((r) => setTimeout(r, 60));
      return {
        buttonRadius: getComputedStyle(btn.shadowRoot.querySelector("button")).borderRadius,
        badgeRadius: getComputedStyle(badge.shadowRoot.querySelector(".badge")).borderRadius,
      };
    });
    assert.equal(result.buttonRadius, "8px"); // --avl-radius-md: 0.5rem
    assert.equal(result.badgeRadius, "999px"); // --avl-radius-pill: 999px
  });
});

// 5. TYPOGRAPHY — a heading using the .avl-type-heading class (base.css)
// whose font-size/weight come from the typography scale tokens.
test("5. typography: an .avl-type-heading element resolves real font-size/weight from the type scale", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    const result = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-command-center");
      const h2 = ws.shadowRoot.querySelector("h2.avl-type-heading");
      const cs = getComputedStyle(h2);
      return { fontSize: cs.fontSize, fontWeight: cs.fontWeight };
    });
    assert.equal(result.fontSize, "20px"); // typography.json heading.size: 1.25rem
    assert.equal(result.fontWeight, "600");
  });
});

// 6. LAYOUT — the app shell's grid track sizes, proving the exact bug
// this fix addresses: before the fix these computed to arbitrary
// content-driven pixel values (observed: ~129px/~1187px/~124px),
// because the whole grid-template-columns declaration was invalid
// (var() referencing nothing) and fell back to implicit auto sizing.
test("6. layout: the app shell's grid columns resolve to the real declared token widths, not content-driven auto-sizing", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    const columns = await page.evaluate(() => {
      const shell = document.querySelector("avl-app-shell").shadowRoot.querySelector(".shell");
      return getComputedStyle(shell).gridTemplateColumns;
    });
    const parts = columns.split(" ").map((v) => parseFloat(v));
    assert.equal(parts[0], 240, "sidebar column must be exactly 15rem (240px), not an auto/content-driven value");
    assert.ok(Math.abs(parts[2] - 320) <= 1, `inspector column must be ~20rem (320px), got ${parts[2]}px`);
  });
});

// 7. MOTION — avl-button's transition-duration, and the reduced-motion
// override collapsing it to effectively instant.
test("7. motion: avl-button's transition-duration resolves to the real --avl-duration-fast value (100ms)", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    const duration = await page.evaluate(async () => {
      const btn = document.createElement("avl-button");
      btn.textContent = "Test";
      document.body.appendChild(btn);
      await new Promise((r) => setTimeout(r, 30));
      return getComputedStyle(btn.shadowRoot.querySelector("button")).transitionDuration;
    });
    assert.match(duration, /0\.1s/);
  });
});

test("7b. motion: prefers-reduced-motion collapses the same duration to ~1ms", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    const duration = await page.evaluate(async () => {
      const btn = document.createElement("avl-button");
      btn.textContent = "Test";
      document.body.appendChild(btn);
      await new Promise((r) => setTimeout(r, 30));
      return getComputedStyle(btn.shadowRoot.querySelector("button")).transitionDuration;
    });
    assert.match(duration, /0\.001s|1ms/);
  });
});

// 8. MULTIPLE WORKSPACES — a component from a different workspace
// (avl-panel, used throughout Dataset Review/Processing/Preview/etc.)
// also resolves real border/text colors, not just the button primitive.
test("8. multiple workspaces: avl-panel (used across many workspaces) resolves real border and text colors", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await page.evaluate(() => {
      location.hash = "#/batches";
    });
    await page.waitForTimeout(250);
    const result = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-batches");
      const panel = ws.shadowRoot.querySelector("avl-panel");
      const titlebar = panel.shadowRoot.querySelector(".titlebar");
      const cs = getComputedStyle(titlebar);
      return { borderBottomColor: cs.borderBottomColor, color: cs.color };
    });
    assert.equal(result.borderBottomColor, hexToRgb(color.themes.light.border.subtle));
    assert.equal(result.color, hexToRgb(color.themes.light.text.secondary));
  });
});

// 9. Whole-document background/color (base.css now also linked at the
// real document root) -- confirms no unstyled flash-of-white/black page
// edge remains around the shell.
test("9. the real document body resolves the canvas background token, not the browser default", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    const bodyBg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    assert.equal(bodyBg, hexToRgb(color.themes.light.surface.canvas));
  });
});
