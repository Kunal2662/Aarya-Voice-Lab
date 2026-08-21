// Real-browser (headless Chromium) tests for VL-D4's Voice Processing +
// Conditioning workspace: the dashboard, processing queue, profiles,
// before/after comparison, quality comparison, processing history,
// feedback, retry, Command Center integration, and the bounded Claude
// processing context. Covers the VL-D4 §36 scenario list. Same
// withPage/collectShadowText pattern as dataset-review.test.mjs.
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
    const LIVE_SNAPSHOT_SUFFIXES = ["/contracts/live/dataset_gate_status.json", "/contracts/live/command_center_snapshot.json"];
    const unexpectedBadResponses = badResponseUrls.filter((url) => !LIVE_SNAPSHOT_SUFFIXES.some((suffix) => url.endsWith(suffix)));
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

async function goToProcessing(page) {
  await page.evaluate(() => {
    location.hash = "#/processing";
  });
  await page.waitForTimeout(200);
}

async function queueFirstRecording(page) {
  await page.evaluate(() => {
    const ws = document.querySelector("avl-workspace-processing");
    const button = [...ws.shadowRoot.querySelectorAll("avl-button")].find((b) => b.textContent.trim() === "Queue for processing");
    button.shadowRoot.querySelector("button").click();
  });
  await page.waitForTimeout(1200);
}

async function selectFirstRecordingRow(page) {
  await page.evaluate(() => {
    const ws = document.querySelector("avl-workspace-processing");
    ws.shadowRoot.querySelector("table tr[data-selectable]").click();
  });
  await page.waitForTimeout(200);
}

test("navigate to Processing: the workspace mounts with a real dashboard", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToProcessing(page);
    const workspaceTag = await page.evaluate(
      () => document.querySelector('avl-app-shell [slot="workspace"]').firstElementChild.tagName.toLowerCase(),
    );
    assert.equal(workspaceTag, "avl-workspace-processing");
    const metrics = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-processing");
      return [...ws.shadowRoot.querySelectorAll(".dashboard avl-stat-tile")].map((m) => m.getAttribute("label"));
    });
    assert.deepEqual(metrics, [
      "Total selected",
      "Queued",
      "Processing",
      "Success",
      "Warning",
      "Failed",
      "Blocked",
      "Cancelled",
      "Avg duration",
      "Quality improved",
      "Quality degraded",
    ]);
  });
});

test("select a recording: the recordings table drives selection and reveals Before/After", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToProcessing(page);
    await selectFirstRecordingRow(page);
    const hasComparison = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-processing");
      return !!ws.shadowRoot.querySelector("avl-before-after-comparison");
    });
    assert.equal(hasComparison, true);
  });
});

test("select a processing profile: the default profile is created and usable", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToProcessing(page);
    const profileRow = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-processing");
      const editor = ws.shadowRoot.querySelector("avl-processing-profile-editor");
      const row = editor.shadowRoot.querySelector("tbody tr");
      return row ? row.textContent.replace(/\s+/g, " ").trim() : null;
    });
    assert.match(profileRow, /standard/);
  });
});

test("queue processing: enqueuing a recording creates a real queue item", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToProcessing(page);
    await queueFirstRecording(page);
    const queueRow = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-processing");
      const queueEl = ws.shadowRoot.querySelector("avl-processing-queue");
      return queueEl.shadowRoot.querySelector("tbody tr")?.textContent.replace(/\s+/g, " ").trim() || null;
    });
    assert.match(queueRow, /synthetic-rec-0001/);
  });
});

test("show progress: intermediate statuses render before the terminal one", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToProcessing(page);
    const sawIntermediate = await page.evaluate(async () => {
      const ws = document.querySelector("avl-workspace-processing");
      const button = [...ws.shadowRoot.querySelectorAll("avl-button")].find((b) => b.textContent.trim() === "Queue for processing");
      button.shadowRoot.querySelector("button").click();
      await new Promise((r) => setTimeout(r, 200));
      const queueEl = ws.shadowRoot.querySelector("avl-processing-queue");
      const badge = queueEl.shadowRoot.querySelector("avl-status-badge");
      const stateNow = badge ? badge.getAttribute("state") : null;
      return stateNow !== "SUCCESS" && stateNow !== null;
    });
    assert.equal(sawIntermediate, true, "an early snapshot should show a non-terminal status");
  });
});

test("show derived artifact: a successful run reports an output path and hash", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToProcessing(page);
    await queueFirstRecording(page);
    await selectFirstRecordingRow(page);
    const artifactText = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-processing");
      const comparison = ws.shadowRoot.querySelector("avl-before-after-comparison");
      return comparison.shadowRoot.textContent;
    });
    assert.match(artifactText, /Output path/);
    assert.match(artifactText, /proc-0000-synthetic-rec-0001\.normalized\.wav/);
  });
});

test("show before/after: source and derived columns both render", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToProcessing(page);
    await queueFirstRecording(page);
    await selectFirstRecordingRow(page);
    const headings = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-processing");
      const comparison = ws.shadowRoot.querySelector("avl-before-after-comparison");
      return [...comparison.shadowRoot.querySelectorAll("h4")].map((h) => h.textContent);
    });
    assert.deepEqual(headings, ["Source", "Derived"]);
  });
});

test("inspect quality comparison: before/after quality panels render real measurements", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToProcessing(page);
    await queueFirstRecording(page);
    await selectFirstRecordingRow(page);
    const text = await page.evaluate(() => {
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
      const ws = document.querySelector("avl-workspace-processing");
      const comparison = ws.shadowRoot.querySelector("avl-before-after-comparison");
      return collect(comparison.shadowRoot);
    });
    assert.match(text, /Estimated SNR/);
  });
});

test("inspect provenance: the Processing Inspector section reports profile/output/artifact identity", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToProcessing(page);
    await queueFirstRecording(page);
    await selectFirstRecordingRow(page);
    const text = await page.evaluate(() => {
      const inspectorRouter = document.querySelector("avl-inspector-router");
      const details = [...inspectorRouter.shadowRoot.querySelectorAll("details")].find(
        (d) => d.querySelector("summary").textContent === "Processing",
      );
      return details.textContent.replace(/\s+/g, " ");
    });
    assert.match(text, /Artifact ID/);
    assert.match(text, /Output SHA-256/);
    assert.match(text, /Profile/);
  });
});

test("review processing history: a queued run is recorded and listed", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToProcessing(page);
    await queueFirstRecording(page);
    await selectFirstRecordingRow(page);
    const historyCount = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-processing");
      const panel = ws.shadowRoot.querySelector("avl-processing-history-panel");
      return panel.shadowRoot.querySelectorAll("li").length;
    });
    assert.equal(historyCount, 1);
  });
});

test("submit processing feedback: a category and comment are recorded", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToProcessing(page);
    await queueFirstRecording(page);
    await selectFirstRecordingRow(page);
    const status = await page.evaluate(async () => {
      const ws = document.querySelector("avl-workspace-processing");
      const form = ws.shadowRoot.querySelector("avl-processing-feedback-form");
      const submit = [...form.shadowRoot.querySelectorAll("avl-button")].find((b) => b.textContent.trim() === "Submit feedback");
      submit.shadowRoot.querySelector("button").click();
      await new Promise((r) => setTimeout(r, 50));
      return form.shadowRoot.querySelector(".status").textContent;
    });
    assert.match(status, /Recorded feedback-\d+/);
  });
});

test("trigger failure state: a blocked recording reports BLOCKED, not a silent success", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToProcessing(page);
    const blockedStatus = await page.evaluate(async () => {
      const ws = document.querySelector("avl-workspace-processing");
      const rows = [...ws.shadowRoot.querySelectorAll("table tbody tr")];
      const blockedRow = rows.find((r) => r.textContent.includes("0003"));
      const button = [...blockedRow.querySelectorAll("avl-button")].find((b) => b.textContent.trim() === "Queue for processing");
      button.shadowRoot.querySelector("button").click();
      await new Promise((r) => setTimeout(r, 1200));
      const queueEl = ws.shadowRoot.querySelector("avl-processing-queue");
      const rowEl = [...queueEl.shadowRoot.querySelectorAll("tbody tr")].find((r) => r.textContent.includes("0003"));
      return rowEl.querySelector("avl-status-badge").getAttribute("state");
    });
    assert.equal(blockedStatus, "BLOCKED");
  });
});

test("retry: a retryable item can be retried from the queue", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToProcessing(page);
    const hasRetry = await page.evaluate(async () => {
      const ws = document.querySelector("avl-workspace-processing");
      const rows = [...ws.shadowRoot.querySelectorAll("table tbody tr")];
      const warnRow = rows.find((r) => r.textContent.includes("0002"));
      const button = [...warnRow.querySelectorAll("avl-button")].find((b) => b.textContent.trim() === "Queue for processing");
      button.shadowRoot.querySelector("button").click();
      await new Promise((r) => setTimeout(r, 1200));
      const queueEl = ws.shadowRoot.querySelector("avl-processing-queue");
      const rowEl = [...queueEl.shadowRoot.querySelectorAll("tbody tr")].find((r) => r.textContent.includes("0002"));
      return [...rowEl.querySelectorAll("avl-button")].some((b) => b.textContent.trim() === "Retry");
    });
    assert.equal(hasRetry, true, "a WARNING item must offer Retry");
  });
});

test("Command Center's Processing panel shows real, live-updating counts", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToProcessing(page);
    await queueFirstRecording(page);
    await page.evaluate(() => {
      location.hash = "#/command-center";
    });
    await page.waitForTimeout(200);
    const metrics = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-command-center");
      const panels = [...ws.shadowRoot.querySelectorAll("avl-panel")];
      const processing = panels.find((p) => p.getAttribute("title") === "Processing");
      return [...processing.querySelectorAll("avl-metric-placeholder")].map((m) => `${m.getAttribute("label")}=${m.getAttribute("value")}`);
    });
    assert.ok(metrics.includes("Total processed=1"));
    assert.ok(metrics.includes("Success=1"));
  });
});

test("Claude processing context is bounded and never includes a filesystem path or speaker field", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToProcessing(page);
    await queueFirstRecording(page);
    await selectFirstRecordingRow(page);
    const contextText = await page.evaluate(() => {
      const inspectorRouter = document.querySelector("avl-inspector-router");
      const el = inspectorRouter.shadowRoot.querySelector("avl-claude-processing-context");
      return el.shadowRoot.querySelector("pre").textContent;
    });
    const context = JSON.parse(contextText);
    assert.deepEqual(Object.keys(context).sort(), ["batch_id", "config", "error", "metric", "permissions", "provenance", "recording_id", "stage", "warning"]);
    assert.equal(context.stage, "voice_processing");
    assert.equal(context.permissions.max_risk_tier, "read_only");
    assert.doesNotMatch(contextText, /\/home\//);
    assert.doesNotMatch(contextText, /speaker/i);
  });
});
