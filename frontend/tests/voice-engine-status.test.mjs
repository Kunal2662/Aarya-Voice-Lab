// Real Voice Model Engine milestone -- real-browser tests for the Models
// workspace's new "Voice Model Engine -- provider capability" panel.
// Same withServer/collectShadowText pattern as app-smoke.test.mjs.
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

async function withServer(fn) {
  const server = createStaticServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  try {
    await fn(`http://127.0.0.1:${port}`);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
}

async function collectShadowText(page, selector) {
  return page.evaluate((sel) => {
    function collect(root) {
      let text = "";
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
        acceptNode(n) {
          return n.parentElement && n.parentElement.tagName === "STYLE" ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
        },
      });
      let n;
      while ((n = walker.nextNode())) text += n.textContent + " ";
      const elWalker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
      let e;
      while ((e = elWalker.nextNode())) {
        if (e.shadowRoot) text += collect(e.shadowRoot);
      }
      return text;
    }
    const el = document.querySelector(sel);
    return el ? collect(el.shadowRoot || el) : null;
  }, selector);
}

test("Models workspace shows an honest Voice Model Engine capability panel", { timeout: 30_000 }, async () => {
  const playwright = await loadPlaywright();
  const browser = await playwright.chromium.launch({ executablePath: CHROMIUM_EXECUTABLE, args: ["--no-sandbox"] });
  try {
    await withServer(async (baseUrl) => {
      const page = await browser.newPage();
      await page.goto(`${baseUrl}/app/index.html`, { waitUntil: "networkidle" });
      await page.evaluate(() => {
        location.hash = "#/models";
      });
      await page.waitForTimeout(300);

      const text = await collectShadowText(page, "avl-workspace-models");
      assert.match(text, /Voice Model Engine/);

      // Whatever the live-snapshot fetch outcome (present in this sandbox
      // vs. absent in a fresh clone), the panel must say ONE of these two
      // honest things -- never silently show nothing, and never claim a
      // provider is AVAILABLE when it isn't.
      const notFetched = /No live capability snapshot fetched yet/.test(text);
      const fetched = /Embedding: /.test(text) && /Generation: /.test(text) && /Training: /.test(text);
      assert.ok(notFetched || fetched, `panel showed neither the "not fetched" state nor real provider rows: ${text}`);

      if (fetched) {
        // The synthetic provider must never be badged as if it were a
        // real capability state -- it gets an explicit synthetic label.
        assert.match(text, /SYNTHETIC.*deterministic test provider/i);
        // Real ML Runtime milestone: `.envs/env-nemo` may or may not be
        // built in the sandbox that runs this test (it is a multi-GB,
        // gitignored, locally-built artifact -- see docs/NEMO.md), so
        // this panel legitimately renders AVAILABLE for the embedding
        // provider on a machine that built it, and NOT_CONFIGURED on one
        // that didn't. Both are honest; neither is asserted here.
        // Generation and training have no real runtime installed in this
        // milestone's scope (voice generation was explicitly deferred --
        // see docs/REAL_ML_RUNTIME_INTEGRATION.md) and must never claim
        // AVAILABLE regardless of what the embedding row says.
        // collectShadowText joins everything with spaces (no row
        // separators), so bound each row's text to the next known label
        // before checking it -- an unbounded match could cross into a
        // later row's state.
        const generationSegment = text.slice(text.indexOf("Generation: "), text.indexOf("Training: "));
        assert.doesNotMatch(
          generationSegment,
          /AVAILABLE/,
          "generation has no real runtime installed this milestone -- AVAILABLE would be a fabricated claim",
        );
        const trainingSegment = text.slice(text.indexOf("Training: "));
        assert.doesNotMatch(
          trainingSegment,
          /AVAILABLE/,
          "training has no real runtime installed this milestone -- AVAILABLE would be a fabricated claim",
        );
      }
      await page.close();
    });
  } finally {
    await browser.close();
  }
});

test("Models workspace's engine panel badges use the honest training_provider_state/generation_backend_state domains", { timeout: 30_000 }, async () => {
  const playwright = await loadPlaywright();
  const browser = await playwright.chromium.launch({ executablePath: CHROMIUM_EXECUTABLE, args: ["--no-sandbox"] });
  try {
    await withServer(async (baseUrl) => {
      const page = await browser.newPage();
      await page.goto(`${baseUrl}/app/index.html`, { waitUntil: "networkidle" });
      await page.evaluate(() => {
        location.hash = "#/models";
      });
      await page.waitForTimeout(300);

      const badgeDomains = await page.evaluate(() => {
        const ws = document.querySelector("avl-workspace-models");
        const badges = [...ws.shadowRoot.querySelectorAll("avl-status-badge")];
        return badges.map((b) => ({ domain: b.getAttribute("domain"), state: b.getAttribute("state") }));
      });

      // Either no live snapshot was fetched (zero badges -- the honest
      // "not fetched" text renders instead), or every badge names a real
      // status domain and a real state within it.
      for (const { domain, state } of badgeDomains) {
        assert.ok(["training_provider_state", "generation_backend_state"].includes(domain), `unexpected domain: ${domain}`);
        assert.ok(state && state.length > 0, "badge must have a real state, never blank");
      }
      await page.close();
    });
  } finally {
    await browser.close();
  }
});
