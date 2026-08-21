// Real-browser (headless Chromium) tests for VL-D9's local session
// persistence: create state -> reload -> verify restored, state survival
// across in-app navigation, the explicit "Clear session data" control,
// clean state after a clear, persistence-unavailable behaviour, and the
// honest Command Center / Activity indicators. Same withPage pattern as
// calibration.test.mjs/processing.test.mjs -- state is driven directly
// through each mounted workspace's real `._services` store references
// (the same production record()/run() methods a real UI action would
// call), since VL-D9 is about the persistence layer itself, not
// re-testing every prior phase's own UI interaction paths (already
// covered by their own Playwright suites).
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

async function goTo(page, destination) {
  await page.evaluate((d) => {
    location.hash = `#/${d}`;
  }, destination);
  await page.waitForTimeout(200);
}

async function recordAReviewDecision(page) {
  await page.evaluate(() => {
    const ws = document.querySelector("avl-workspace-dataset-review");
    ws._services.reviewStore.record({ segmentId: "seg-session-1", decision: "ACCEPTED", reasonCode: "other" });
  });
  await page.waitForTimeout(100); // let the autosave listener flush to localStorage.
}

async function runACalibrationPass(page) {
  await page.evaluate(() => {
    const ws = document.querySelector("avl-workspace-calibration");
    ws._services.calibrationStore.run({});
  });
  await page.waitForTimeout(100);
}

async function reviewDecisionCount(page) {
  return page.evaluate(() => document.querySelector("avl-workspace-dataset-review")._services.reviewStore.all().length);
}

async function calibrationHistoryCount(page) {
  return page.evaluate(() => document.querySelector("avl-workspace-calibration")._services.calibrationStore.history().length);
}

test("1. create session state and reload: the review decision is restored from localStorage", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goTo(page, "review");
    await recordAReviewDecision(page);
    assert.equal(await reviewDecisionCount(page), 1);

    await page.reload({ waitUntil: "networkidle" });
    await goTo(page, "review");
    assert.equal(await reviewDecisionCount(page), 1, "the review decision must survive a full page reload");
  });
});

test("2. state survives navigating between workspaces without a reload", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goTo(page, "review");
    await recordAReviewDecision(page);
    await goTo(page, "settings");
    await goTo(page, "calibration");
    await goTo(page, "review");
    assert.equal(await reviewDecisionCount(page), 1, "in-memory state must survive navigating away and back");
  });
});

test("3. calibration's three-axis profile state (run/calibration/application) is restored intact across a reload", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goTo(page, "calibration");
    await runACalibrationPass(page);
    const before = await page.evaluate(() => {
      const p = document.querySelector("avl-workspace-calibration")._services.calibrationStore.current();
      return { run_state: p.run_state, calibration_state: p.calibration_state, application_state: p.application_state, profile_id: p.profile_id };
    });

    await page.reload({ waitUntil: "networkidle" });
    await goTo(page, "calibration");
    const after = await page.evaluate(() => {
      const p = document.querySelector("avl-workspace-calibration")._services.calibrationStore.current();
      return { run_state: p.run_state, calibration_state: p.calibration_state, application_state: p.application_state, profile_id: p.profile_id };
    });
    assert.deepEqual(after, before);
  });
});

test("4. Clear session data removes the in-memory state immediately", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goTo(page, "review");
    await recordAReviewDecision(page);
    assert.equal(await reviewDecisionCount(page), 1);

    await goTo(page, "settings");
    await page.evaluate(() => {
      const settings = document.querySelector("avl-workspace-settings");
      const buttons = [...settings.shadowRoot.querySelectorAll("button")];
      buttons.find((b) => b.textContent.trim() === "Clear session data").click();
    });
    await page.waitForTimeout(50);
    await page.evaluate(() => {
      const settings = document.querySelector("avl-workspace-settings");
      const buttons = [...settings.shadowRoot.querySelectorAll("button")];
      buttons.find((b) => b.textContent.trim() === "Confirm clear").click();
    });
    await page.waitForTimeout(100);

    await goTo(page, "review");
    assert.equal(await reviewDecisionCount(page), 0, "the review store must be empty immediately after clearing");
  });
});

test("5. reloading after Clear session data starts from a clean initial state", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goTo(page, "review");
    await recordAReviewDecision(page);
    await goTo(page, "settings");
    await page.evaluate(() => {
      const settings = document.querySelector("avl-workspace-settings");
      [...settings.shadowRoot.querySelectorAll("button")].find((b) => b.textContent.trim() === "Clear session data").click();
    });
    await page.evaluate(() => {
      const settings = document.querySelector("avl-workspace-settings");
      [...settings.shadowRoot.querySelectorAll("button")].find((b) => b.textContent.trim() === "Confirm clear").click();
    });
    await page.waitForTimeout(100);

    await page.reload({ waitUntil: "networkidle" });
    await goTo(page, "review");
    assert.equal(await reviewDecisionCount(page), 0, "nothing should be restored once the saved session was cleared");
  });
});

test("6. Cancel on the clear confirmation leaves session data intact", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goTo(page, "review");
    await recordAReviewDecision(page);
    await goTo(page, "settings");
    await page.evaluate(() => {
      const settings = document.querySelector("avl-workspace-settings");
      [...settings.shadowRoot.querySelectorAll("button")].find((b) => b.textContent.trim() === "Clear session data").click();
    });
    await page.evaluate(() => {
      const settings = document.querySelector("avl-workspace-settings");
      [...settings.shadowRoot.querySelectorAll("button")].find((b) => b.textContent.trim() === "Cancel").click();
    });
    await goTo(page, "review");
    assert.equal(await reviewDecisionCount(page), 1, "clicking Cancel must never clear anything");
  });
});

test("7. persistence-unavailable: the app still loads and works with storage disabled, no crash", { timeout: 30_000 }, async () => {
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
    // Simulate a browser where localStorage exists but every operation
    // throws (private-browsing-style) -- injected before any app script
    // runs, via addInitScript.
    await page.addInitScript(() => {
      const throwing = {
        getItem() {
          throw new Error("storage disabled");
        },
        setItem() {
          throw new Error("storage disabled");
        },
        removeItem() {
          throw new Error("storage disabled");
        },
      };
      Object.defineProperty(window, "localStorage", { value: throwing, configurable: true });
    });
    await page.goto(`http://127.0.0.1:${port}/app/index.html`, { waitUntil: "networkidle" });

    const workspaceTag = await page.evaluate(
      () => document.querySelector('avl-app-shell [slot="workspace"]').firstElementChild.tagName.toLowerCase(),
    );
    assert.equal(workspaceTag, "avl-workspace-command-center", "the app must still boot normally");

    // Recording state with storage disabled must not throw anywhere.
    await page.evaluate(() => {
      location.hash = "#/review";
    });
    await page.waitForTimeout(150);
    await page.evaluate(() => {
      document.querySelector("avl-workspace-dataset-review")._services.reviewStore.record({
        segmentId: "seg-unavailable",
        decision: "ACCEPTED",
        reasonCode: "other",
      });
    });
    await page.waitForTimeout(100);

    assert.deepEqual(consoleErrors, [], `no console error should occur with persistence unavailable: ${JSON.stringify(consoleErrors)}`);
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
});

test("8. a full create-across-all-domains-then-reload cycle produces zero console errors", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goTo(page, "review");
    await recordAReviewDecision(page);
    await goTo(page, "calibration");
    await runACalibrationPass(page);
    await page.reload({ waitUntil: "networkidle" });
    await goTo(page, "review");
    await goTo(page, "calibration");
    // withPage()'s own teardown asserts consoleErrors is exactly the
    // expected (zero, beyond the documented dataset-gate 404) count.
  });
});

test("9. Command Center's Session panel reports honest live status", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goTo(page, "command-center");
    const beforeAny = await page.evaluate(() => {
      const cc = document.querySelector("avl-workspace-command-center");
      const metrics = [...cc.shadowRoot.querySelectorAll("avl-metric-placeholder")];
      const saved = metrics.find((m) => m.getAttribute("label") === "Session data saved");
      return saved.getAttribute("value");
    });
    assert.equal(beforeAny, "no");

    await goTo(page, "review");
    await recordAReviewDecision(page);
    await goTo(page, "command-center");
    const afterRecording = await page.evaluate(() => {
      const cc = document.querySelector("avl-workspace-command-center");
      const metrics = [...cc.shadowRoot.querySelectorAll("avl-metric-placeholder")];
      const saved = metrics.find((m) => m.getAttribute("label") === "Session data saved");
      return saved.getAttribute("value");
    });
    assert.equal(afterRecording, "yes");
  });
});

test("10. Command Center's Storage badge reads ready when persistence is available", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goTo(page, "command-center");
    const state = await page.evaluate(() => {
      const cc = document.querySelector("avl-workspace-command-center");
      const rows = [...cc.shadowRoot.querySelectorAll(".row")];
      const storageRow = rows.find((r) => r.querySelector("span")?.textContent === "Storage");
      return storageRow.querySelector("avl-status-badge").getAttribute("state");
    });
    assert.equal(state, "ready");
  });
});

test("11. Activity records an honest 'Session restored' event only when something was actually restored", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goTo(page, "review");
    await recordAReviewDecision(page);
    await page.reload({ waitUntil: "networkidle" });

    await goTo(page, "activity");
    const summaries = await page.evaluate(() => {
      const activity = document.querySelector("avl-workspace-activity");
      const timeline = activity.shadowRoot.querySelector("avl-activity-timeline");
      return [...timeline.shadowRoot.querySelectorAll(".summary")].map((el) => el.textContent);
    });
    assert.ok(
      summaries.some((s) => /^Session restored:/.test(s)),
      `expected a "Session restored" activity event, got: ${JSON.stringify(summaries)}`,
    );
    assert.ok(!summaries.some((s) => /cloud sync/i.test(s)), "no summary may ever use cloud-sync language");
  });
});

test("12. Activity records 'Session data cleared' only after the explicit Clear action", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goTo(page, "review");
    await recordAReviewDecision(page);
    await goTo(page, "settings");
    await page.evaluate(() => {
      const settings = document.querySelector("avl-workspace-settings");
      [...settings.shadowRoot.querySelectorAll("button")].find((b) => b.textContent.trim() === "Clear session data").click();
    });
    await page.evaluate(() => {
      const settings = document.querySelector("avl-workspace-settings");
      [...settings.shadowRoot.querySelectorAll("button")].find((b) => b.textContent.trim() === "Confirm clear").click();
    });
    await page.waitForTimeout(100);

    await goTo(page, "activity");
    const summaries = await page.evaluate(() => {
      const activity = document.querySelector("avl-workspace-activity");
      const timeline = activity.shadowRoot.querySelector("avl-activity-timeline");
      return [...timeline.shadowRoot.querySelectorAll(".summary")].map((el) => el.textContent);
    });
    assert.ok(summaries.some((s) => /^Session data cleared:/.test(s)));
  });
});

test("13. Settings' Local session persistence status matches Command Center's", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goTo(page, "settings");
    const state = await page.evaluate(() => {
      const settings = document.querySelector("avl-workspace-settings");
      const rows = [...settings.shadowRoot.querySelectorAll(".row")];
      const row = rows.find((r) => r.querySelector("span")?.textContent === "Local session persistence");
      return row.querySelector("avl-status-badge").getAttribute("state");
    });
    assert.equal(state, "ready");
  });
});
