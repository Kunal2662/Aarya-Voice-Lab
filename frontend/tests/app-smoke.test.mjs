// Real-browser smoke test for the VL-D1 operational app (frontend/app/),
// distinct from VL-D0's tests/browser-smoke.test.mjs which only exercises
// the design-system wireframe. Serves frontend/ and drives navigation,
// selection, and the Claude fix-flow through actual DOM events in
// headless Chromium.
import { test } from "node:test";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { createStaticServer } from "../tools/serve.mjs";

const PLAYWRIGHT_INDEX = "/opt/node22/lib/node_modules/playwright/index.js";
const CHROMIUM_EXECUTABLE = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";

const DESTINATIONS = [
  "command-center",
  "import",
  "batches",
  "recordings",
  "review",
  "processing",
  "pipeline",
  "voices",
  "models",
  "calibration",
  "claude",
  "activity",
  "settings",
];

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

test("app navigates through all 11 VL-D1 workspaces with no console errors", { timeout: 60_000 }, async () => {
  const playwright = await loadPlaywright();
  const browser = await playwright.chromium.launch({ executablePath: CHROMIUM_EXECUTABLE, args: ["--no-sandbox"] });
  try {
    await withServer(async (baseUrl) => {
      const page = await browser.newPage();
      const consoleErrors = [];
      page.on("console", (msg) => {
        if (msg.type() === "error") consoleErrors.push(msg.text());
      });
      page.on("pageerror", (err) => consoleErrors.push(String(err)));

      // The Import workspace fetches frontend/contracts/live/dataset_gate_status.json,
      // which is deliberately gitignored (a live, host-specific snapshot —
      // see scripts/export_dataset_gate_status.py) and legitimately absent
      // in a fresh clone. workspace-import.js already handles that fetch
      // failure and falls back to an honest "not evaluated" state, but
      // Chromium still logs the failed resource load as a console error
      // regardless of the JS-level try/catch. Track the actual failing
      // URL so this test can allow exactly that one, known case rather
      // than loosening the assertion for console errors in general.
      const badResponseUrls = [];
      page.on("response", (response) => {
        if (response.status() >= 400) badResponseUrls.push(response.url());
      });

      await page.goto(`${baseUrl}/app/index.html`, { waitUntil: "networkidle" });

      for (const destination of DESTINATIONS) {
        await page.evaluate((dest) => {
          location.hash = `#/${dest}`;
        }, destination);
        await page.waitForTimeout(150);
        const workspaceTag = await page.evaluate(() => {
          const mount = document.querySelector('avl-app-shell [slot="workspace"]');
          return mount && mount.firstElementChild ? mount.firstElementChild.tagName.toLowerCase() : null;
        });
        assert.ok(workspaceTag && workspaceTag.startsWith("avl-workspace-"), `no workspace mounted for #/${destination}`);
        const activeSidebarDestination = await page.evaluate(() => {
          const nav = document.querySelector("avl-sidebar-nav");
          const active = nav.querySelector("avl-sidebar-item[active]");
          return active ? active.getAttribute("destination") : null;
        });
        assert.equal(activeSidebarDestination, destination, "sidebar active state did not follow navigation");
      }

      const unexpectedBadResponses = badResponseUrls.filter((url) => !url.endsWith("/contracts/live/dataset_gate_status.json"));
      assert.deepEqual(unexpectedBadResponses, [], `unexpected failed requests: ${unexpectedBadResponses.join("; ")}`);

      const expected404Count = badResponseUrls.length - unexpectedBadResponses.length;
      assert.equal(
        consoleErrors.length,
        expected404Count,
        `console errors beyond the expected dataset-gate-snapshot 404: ${JSON.stringify(consoleErrors)}`,
      );
      await page.close();
    });
  } finally {
    await browser.close();
  }
});

test("selecting a batch updates the Inspector with real batch data", { timeout: 30_000 }, async () => {
  const playwright = await loadPlaywright();
  const browser = await playwright.chromium.launch({ executablePath: CHROMIUM_EXECUTABLE, args: ["--no-sandbox"] });
  try {
    await withServer(async (baseUrl) => {
      const page = await browser.newPage();
      await page.goto(`${baseUrl}/app/index.html`, { waitUntil: "networkidle" });
      await page.evaluate(() => {
        location.hash = "#/batches";
      });
      await page.waitForTimeout(200);
      await page.evaluate(() => {
        const mount = document.querySelector('avl-app-shell [slot="workspace"]').firstElementChild;
        const card = mount.shadowRoot.querySelector("avl-batch-card");
        card.shadowRoot.querySelector("avl-card").click();
      });
      await page.waitForTimeout(150);
      const inspectorText = await collectShadowText(page, "avl-inspector-router");
      assert.match(inspectorText, /synthetic-batch-001/);
      await page.close();
    });
  } finally {
    await browser.close();
  }
});

test("selecting a pipeline stage updates the Inspector and never reorders backend stage data", { timeout: 30_000 }, async () => {
  const playwright = await loadPlaywright();
  const browser = await playwright.chromium.launch({ executablePath: CHROMIUM_EXECUTABLE, args: ["--no-sandbox"] });
  try {
    await withServer(async (baseUrl) => {
      const page = await browser.newPage();
      await page.goto(`${baseUrl}/app/index.html`, { waitUntil: "networkidle" });
      await page.evaluate(() => {
        location.hash = "#/pipeline";
      });
      await page.waitForTimeout(200);
      await page.evaluate(() => {
        const mount = document.querySelector('avl-app-shell [slot="workspace"]').firstElementChild;
        const track = mount.shadowRoot.querySelector("avl-pipeline-stage-track");
        const node = track.shadowRoot.querySelector("avl-pipeline-stage-node");
        node.shadowRoot.querySelector("button").click();
      });
      await page.waitForTimeout(150);
      const inspectorText = await collectShadowText(page, "avl-inspector-router");
      // The first stage in canonical pipeline order is "source".
      assert.match(inspectorText, /source/);
      await page.close();
    });
  } finally {
    await browser.close();
  }
});

test("the import workspace shows the real (gitignored) dataset gate snapshot honestly, never fabricating access", { timeout: 30_000 }, async () => {
  const playwright = await loadPlaywright();
  const browser = await playwright.chromium.launch({ executablePath: CHROMIUM_EXECUTABLE, args: ["--no-sandbox"] });
  try {
    await withServer(async (baseUrl) => {
      const page = await browser.newPage();
      await page.goto(`${baseUrl}/app/index.html`, { waitUntil: "networkidle" });
      await page.evaluate(() => {
        location.hash = "#/import";
      });
      await page.waitForTimeout(200);
      const workspaceTag = "avl-workspace-import";
      const text = await collectShadowText(page, workspaceTag);
      // VL-D2: the import workspace now does real client-side hashing —
      // the honesty boundary moved from "nothing is hashed" to "nothing
      // is written into source/" (no execution transport exists to do
      // that). See docs/VLD2_DATASET_WORKSPACE.md.
      assert.match(text, /nothing is written into source\//i);
      // Either the live snapshot renders its real unsatisfied-condition
      // count, or the honest "not evaluated" fallback shows — never a
      // bare "access granted" claim with no evidence.
      assert.ok(/conditions unsatisfied/.test(text) || /not evaluated in this session/.test(text));
      assert.doesNotMatch(text, /access[- ]?allowed:?\s*true/i);
      await page.close();
    });
  } finally {
    await browser.close();
  }
});

test("the Claude fix-flow is honest about having no execution transport in VL-D1", { timeout: 30_000 }, async () => {
  const playwright = await loadPlaywright();
  const browser = await playwright.chromium.launch({ executablePath: CHROMIUM_EXECUTABLE, args: ["--no-sandbox"] });
  try {
    await withServer(async (baseUrl) => {
      const page = await browser.newPage();
      await page.goto(`${baseUrl}/app/index.html`, { waitUntil: "networkidle" });
      await page.evaluate(() => {
        location.hash = "#/claude";
      });
      await page.waitForTimeout(200);
      await page.evaluate(() => {
        const mount = document.querySelector('avl-app-shell [slot="workspace"]').firstElementChild;
        const flow = mount.shadowRoot.querySelector("avl-claude-fix-flow");
        flow.shadowRoot.querySelector("avl-button").shadowRoot.querySelector("button").click();
      });
      await page.waitForTimeout(150);
      await page.evaluate(() => {
        const mount = document.querySelector('avl-app-shell [slot="workspace"]').firstElementChild;
        const flow = mount.shadowRoot.querySelector("avl-claude-fix-flow");
        flow.shadowRoot.querySelector("avl-button").shadowRoot.querySelector("button").click();
      });
      await page.waitForTimeout(300);
      const text = await page.evaluate(() => {
        const mount = document.querySelector('avl-app-shell [slot="workspace"]').firstElementChild;
        const flow = mount.shadowRoot.querySelector("avl-claude-fix-flow");
        function collect(root) {
          let t = "";
          const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
            acceptNode(n) {
              return n.parentElement && n.parentElement.tagName === "STYLE" ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
            },
          });
          let n;
          while ((n = w.nextNode())) t += n.textContent + " ";
          const ew = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
          let e;
          while ((e = ew.nextNode())) if (e.shadowRoot) t += collect(e.shadowRoot);
          return t;
        }
        return collect(flow.shadowRoot);
      });
      assert.match(text, /No execution transport is connected in VL-D1/);
      await page.close();
    });
  } finally {
    await browser.close();
  }
});
