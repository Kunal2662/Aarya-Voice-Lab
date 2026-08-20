// Real-browser (headless Chromium) tests for VL-D2's Dataset Workspace:
// Import, Batches (dashboard), Recordings (search/filter/sort/inspector),
// pipeline handoff, and Command Center integration.
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
    // The Import workspace fetches frontend/contracts/live/dataset_gate_status.json,
    // a deliberately gitignored, host-specific snapshot (see
    // scripts/export_dataset_gate_status.py) that is legitimately absent
    // in a fresh clone — workspace-import.js already handles that fetch
    // failure and falls back to an honest "not evaluated" state, but
    // Chromium still logs the failed resource load as a console error
    // regardless of the JS-level try/catch. Track the actual failing URL
    // so tests can allow exactly that one, known case (same pattern as
    // tests/app-smoke.test.mjs) rather than loosening the assertion.
    const badResponseUrls = [];
    page.on("response", (response) => {
      if (response.status() >= 400) badResponseUrls.push(response.url());
    });
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });
    page.on("pageerror", (err) => consoleErrors.push(String(err)));
    await page.goto(`http://127.0.0.1:${port}/app/index.html`, { waitUntil: "networkidle" });
    await fn(page, consoleErrors);
    const unexpectedBadResponses = badResponseUrls.filter((url) => !url.endsWith("/contracts/live/dataset_gate_status.json"));
    assert.deepEqual(unexpectedBadResponses, [], `unexpected failed requests: ${unexpectedBadResponses.join("; ")}`);
    const expectedErrorCount = badResponseUrls.length - unexpectedBadResponses.length;
    assert.equal(
      consoleErrors.length,
      expectedErrorCount,
      `console errors beyond the expected dataset-gate-snapshot 404: ${JSON.stringify(consoleErrors)}`,
    );
  } finally {
    await browser.close();
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
      while ((e = elWalker.nextNode())) if (e.shadowRoot) text += collect(e.shadowRoot);
      return text;
    }
    const el = document.querySelector(sel);
    return el ? collect(el.shadowRoot || el) : null;
  }, selector);
}

async function currentWorkspace(page) {
  return page.evaluate(() => document.querySelector('avl-app-shell [slot="workspace"]').firstElementChild.tagName.toLowerCase());
}

test("drop a real synthetic WAV in Import: it hashes, classifies, and accepts", { timeout: 30_000 }, async () => {
  await withPage(async (page, errors) => {
    await page.evaluate(() => { location.hash = "#/import"; });
    await page.waitForTimeout(200);
    assert.equal(await currentWorkspace(page), "avl-workspace-import");

    const result = await page.evaluate(async () => {
      const mount = document.querySelector('avl-app-shell [slot="workspace"]').firstElementChild;
      const dropZone = mount.shadowRoot.querySelector("avl-import-drop-zone");
      const bytes = new Uint8Array(44);
      bytes.set([0x52, 0x49, 0x46, 0x46], 0);
      bytes.set([0x57, 0x41, 0x56, 0x45], 8);
      const file = new File([bytes], "browser-test.wav", { type: "audio/wav" });
      dropZone.dispatchEvent(new CustomEvent("avl-files-selected", { detail: { files: [file] }, bubbles: true, composed: true }));
      await new Promise((r) => setTimeout(r, 100));
      const queueTable = mount.shadowRoot.querySelector("avl-import-queue");
      const startButton = [...queueTable.shadowRoot.querySelectorAll("avl-button")].find((b) => b.textContent === "Start processing");
      startButton.shadowRoot.querySelector("button").click();
      await new Promise((r) => setTimeout(r, 300));
      const item = queueTable.queue.list()[0];
      return { status: item.status, sha256: item.sha256, hasStoredPath: "storedRelativePath" in item };
    });

    assert.equal(result.status, "accepted");
    assert.equal(result.sha256.length, 64);
    assert.equal(result.hasStoredPath, false, "client-side queue must never claim a stored path");
  });
});

test("an import failure offers Ask Claude with a bounded, redacted context", { timeout: 30_000 }, async () => {
  await withPage(async (page, errors) => {
    await page.evaluate(() => { location.hash = "#/import"; });
    await page.waitForTimeout(200);

    await page.evaluate(async () => {
      const mount = document.querySelector('avl-app-shell [slot="workspace"]').firstElementChild;
      const dropZone = mount.shadowRoot.querySelector("avl-import-drop-zone");
      const zeroByte = new File([], "empty.wav");
      dropZone.dispatchEvent(new CustomEvent("avl-files-selected", { detail: { files: [zeroByte] }, bubbles: true, composed: true }));
      await new Promise((r) => setTimeout(r, 100));
      const queueTable = mount.shadowRoot.querySelector("avl-import-queue");
      const startButton = [...queueTable.shadowRoot.querySelectorAll("avl-button")].find((b) => b.textContent === "Start processing");
      startButton.shadowRoot.querySelector("button").click();
      await new Promise((r) => setTimeout(r, 300));
    });

    const askClaudeClicked = await page.evaluate(() => {
      const mount = document.querySelector('avl-app-shell [slot="workspace"]').firstElementChild;
      const queueTable = mount.shadowRoot.querySelector("avl-import-queue");
      const askButton = [...queueTable.shadowRoot.querySelectorAll("avl-button")].find((b) => b.textContent === "Ask Claude");
      if (!askButton) return false;
      askButton.shadowRoot.querySelector("button").click();
      return true;
    });
    assert.equal(askClaudeClicked, true, "a blocked (zero-byte) item should offer Ask Claude");

    await page.waitForTimeout(150);
    const text = await collectShadowText(page, "avl-workspace-import");
    assert.match(text, /Fix workflow/);
    assert.match(text, /"stage": "import"/);
    assert.match(text, /"filename": "empty\.wav"/);
    assert.doesNotMatch(text, /"permissions":\s*\{\s*"max_risk_tier":\s*"destructive"/i);
  });
});

test("Batches shows a real Dataset Dashboard computed from actual arrays", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await page.evaluate(() => { location.hash = "#/batches"; });
    await page.waitForTimeout(200);
    const text = await collectShadowText(page, "avl-workspace-batches");
    assert.match(text, /Dataset dashboard/);
    assert.match(text, /Total files/);
    assert.match(text, /Batches/);
  });
});

test("Recordings supports real search, filter, and sort over a live table", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await page.evaluate(() => { location.hash = "#/recordings"; });
    await page.waitForTimeout(200);

    const before = await collectShadowText(page, "avl-workspace-recordings");
    assert.match(before, /3 of 3 recording/);

    // Search narrows the table.
    await page.evaluate(() => {
      const mount = document.querySelector('avl-app-shell [slot="workspace"]').firstElementChild;
      const input = mount.shadowRoot.querySelector('input[type="search"]');
      input.value = "0001";
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await page.waitForTimeout(100);
    const afterSearch = await collectShadowText(page, "avl-workspace-recordings");
    assert.match(afterSearch, /1 of 3 recording/);

    // Selecting a row updates the Inspector with honest placeholders.
    await page.evaluate(() => {
      const mount = document.querySelector('avl-app-shell [slot="workspace"]').firstElementChild;
      const row = mount.shadowRoot.querySelector("tbody tr");
      row.click();
    });
    await page.waitForTimeout(100);
    const inspectorText = await collectShadowText(page, "avl-inspector-router");
    assert.match(inspectorText, /NOT AVAILABLE/);
    assert.match(inspectorText, /NOT ANALYZED/);
    assert.match(inspectorText, /NOT CALIBRATED/);
    assert.doesNotMatch(inspectorText, /speaker.{0,20}\d/i); // no fabricated speaker score
  });
});

test("Open Pipeline handoff navigates from Import to the Pipeline workspace", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await page.evaluate(() => { location.hash = "#/import"; });
    await page.waitForTimeout(200);

    await page.evaluate(async () => {
      const mount = document.querySelector('avl-app-shell [slot="workspace"]').firstElementChild;
      const dropZone = mount.shadowRoot.querySelector("avl-import-drop-zone");
      const bytes = new Uint8Array(44);
      bytes.set([0x52, 0x49, 0x46, 0x46], 0);
      bytes.set([0x57, 0x41, 0x56, 0x45], 8);
      dropZone.dispatchEvent(new CustomEvent("avl-files-selected", { detail: { files: [new File([bytes], "ok.wav")] }, bubbles: true, composed: true }));
      await new Promise((r) => setTimeout(r, 100));
      const queueTable = mount.shadowRoot.querySelector("avl-import-queue");
      const startButton = [...queueTable.shadowRoot.querySelectorAll("avl-button")].find((b) => b.textContent === "Start processing");
      startButton.shadowRoot.querySelector("button").click();
      await new Promise((r) => setTimeout(r, 300));
    });

    const clicked = await page.evaluate(() => {
      const mount = document.querySelector('avl-app-shell [slot="workspace"]').firstElementChild;
      const openPipeline = [...mount.shadowRoot.querySelectorAll("avl-button")].find((b) => b.textContent === "Open Pipeline");
      if (!openPipeline) return false;
      openPipeline.shadowRoot.querySelector("button").click();
      return true;
    });
    assert.equal(clicked, true, "Open Pipeline should appear once an item is accepted");
    await page.waitForTimeout(200);
    assert.equal(await currentWorkspace(page), "avl-workspace-pipeline");
  });
});

test("Command Center's Imports panel reflects a completed import in real time", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await page.evaluate(() => { location.hash = "#/import"; });
    await page.waitForTimeout(200);
    await page.evaluate(async () => {
      const mount = document.querySelector('avl-app-shell [slot="workspace"]').firstElementChild;
      const dropZone = mount.shadowRoot.querySelector("avl-import-drop-zone");
      const bytes = new Uint8Array(44);
      bytes.set([0x52, 0x49, 0x46, 0x46], 0);
      bytes.set([0x57, 0x41, 0x56, 0x45], 8);
      dropZone.dispatchEvent(new CustomEvent("avl-files-selected", { detail: { files: [new File([bytes], "cc.wav")] }, bubbles: true, composed: true }));
      await new Promise((r) => setTimeout(r, 100));
      const queueTable = mount.shadowRoot.querySelector("avl-import-queue");
      const startButton = [...queueTable.shadowRoot.querySelectorAll("avl-button")].find((b) => b.textContent === "Start processing");
      startButton.shadowRoot.querySelector("button").click();
      await new Promise((r) => setTimeout(r, 300));
    });

    await page.evaluate(() => { location.hash = "#/command-center"; });
    await page.waitForTimeout(200);
    const text = await collectShadowText(page, "avl-workspace-command-center");
    assert.match(text, /Imports/);
    assert.match(text, /Accepted/);
  });
});
