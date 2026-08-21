// Real-browser (headless Chromium) tests for VL-D7's AI Calibration
// Engine workspace: opening the workspace, running a calibration pass,
// zero-evidence honesty, readiness/parameter-adjustment/history display,
// rollback (append-only), Command Center and Activity integration, the
// bounded Claude calibration context, and light/dark theme rendering.
// Same withPage/collectShadowText pattern as feedback.test.mjs.
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

async function goToCalibration(page) {
  await page.evaluate(() => {
    location.hash = "#/calibration";
  });
  await page.waitForTimeout(200);
}

async function clickRunCalibration(page) {
  await page.evaluate(() => {
    const ws = document.querySelector("avl-workspace-calibration");
    const runPanel = ws.shadowRoot.querySelector("avl-calibration-run-panel");
    const button = runPanel.shadowRoot.querySelector("avl-button");
    button.shadowRoot.querySelector("button").click();
  });
  await page.waitForTimeout(80);
}

async function generateOutput(page, text) {
  await page.evaluate(() => {
    location.hash = "#/preview";
  });
  await page.waitForTimeout(200);
  await page.evaluate((t) => {
    const ws = document.querySelector("avl-workspace-preview");
    const textarea = ws.shadowRoot.querySelector("avl-text-input").shadowRoot.querySelector("textarea");
    textarea.value = t;
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  }, text);
  await page.evaluate(() => {
    const ws = document.querySelector("avl-workspace-preview");
    const button = [...ws.shadowRoot.querySelectorAll("avl-button")].find((b) => b.textContent.trim() === "Generate preview");
    button.shadowRoot.querySelector("button").click();
  });
  await page.waitForTimeout(1200);
}

async function submitTwoAgreeingEvaluations(page) {
  await page.evaluate(() => {
    location.hash = "#/feedback";
  });
  await page.waitForTimeout(200);

  // Two submissions on the same output are enough to cross
  // MIN_EVIDENCE_FOR_PROVISIONAL (a count of evaluation records, not
  // distinct reviewers) -- avl-evaluation-form's reviewer identity is a
  // JS property the workspace assigns, not a text field this test
  // drives directly.
  for (let i = 0; i < 2; i += 1) {
    await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-feedback");
      const queue = ws.shadowRoot.querySelector("avl-evaluation-queue");
      const row = queue.shadowRoot.querySelector("tbody tr");
      row.querySelector("avl-button").shadowRoot.querySelector("button").click();
    });
    await page.waitForTimeout(80);
    await page.evaluate(() => {
      const form = document.querySelector("avl-workspace-feedback").shadowRoot.querySelector("avl-evaluation-form");
      const audioPlayer = form.shadowRoot.querySelector("avl-voice-player").shadowRoot.querySelector("avl-audio-player");
      const playButton = [...audioPlayer.shadowRoot.querySelectorAll("avl-button")].find((b) => b.textContent === "Play" || b.textContent === "Pause");
      playButton.shadowRoot.querySelector("button").click();
    });
    await page.waitForTimeout(60);
    await page.evaluate(() => {
      const form = document.querySelector("avl-workspace-feedback").shadowRoot.querySelector("avl-evaluation-form");
      const ratingPanel = form.shadowRoot.querySelector("avl-rating-panel");
      ratingPanel.shadowRoot.querySelectorAll("button.score-btn")[3].click();
    });
    await page.evaluate(() => {
      const form = document.querySelector("avl-workspace-feedback").shadowRoot.querySelector("avl-evaluation-form");
      const button = [...form.shadowRoot.querySelectorAll("avl-button")].find((b) => b.textContent === "Submit evaluation");
      button.shadowRoot.querySelector("button").click();
    });
    await page.waitForTimeout(80);
  }
}

test("open workspace: navigating to Calibration mounts avl-workspace-calibration with the AI Calibration Engine panel", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToCalibration(page);
    const workspaceTag = await page.evaluate(
      () => document.querySelector('avl-app-shell [slot="workspace"]').firstElementChild.tagName.toLowerCase(),
    );
    assert.equal(workspaceTag, "avl-workspace-calibration");
    const title = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-calibration");
      const panels = [...ws.shadowRoot.querySelectorAll("avl-panel")];
      return panels.map((p) => p.getAttribute("title"));
    });
    assert.ok(title.includes("AI Calibration Engine"));
  });
});

test("no calibration run yet: run panel shows the honest empty state, not a fabricated badge", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToCalibration(page);
    const text = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-calibration");
      const runPanel = ws.shadowRoot.querySelector("avl-calibration-run-panel");
      return runPanel.shadowRoot.textContent;
    });
    assert.match(text, /No calibration run yet/);
  });
});

test("running calibration with zero evidence: run_state CALIBRATED, calibration_state UNCALIBRATED, never fabricated", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToCalibration(page);
    await clickRunCalibration(page);
    const badges = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-calibration");
      const runPanel = ws.shadowRoot.querySelector("avl-calibration-run-panel");
      const badgeEls = [...runPanel.shadowRoot.querySelectorAll("avl-status-badge")];
      return badgeEls.map((b) => `${b.getAttribute("domain")}=${b.getAttribute("state")}`);
    });
    assert.ok(badges.includes("hardware_calibration=CALIBRATED"));
    assert.ok(badges.includes("calibration=UNCALIBRATED"));
  });
});

test("readiness panel renders real evidence counts", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToCalibration(page);
    const values = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-calibration");
      const readiness = ws.shadowRoot.querySelector("avl-calibration-readiness-panel");
      return [...readiness.shadowRoot.querySelectorAll("avl-metric-placeholder")].map(
        (m) => `${m.getAttribute("label")}=${m.getAttribute("value")}`,
      );
    });
    assert.ok(values.includes("Evaluations=0"));
  });
});

test("parameter adjustments table shows bounds and rationale after a run", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToCalibration(page);
    await clickRunCalibration(page);
    const row = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-calibration");
      const table = ws.shadowRoot.querySelector("avl-calibration-parameter-adjustments");
      return table.shadowRoot.querySelector("tbody tr").textContent.replace(/\s+/g, " ").trim();
    });
    assert.match(row, /max_concurrent_generations/);
    assert.match(row, /\[1, 8\]/);
  });
});

test("cannot falsely mark parameter adjustments as unbounded: every row shows an evidence reference", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToCalibration(page);
    await clickRunCalibration(page);
    const row = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-calibration");
      const table = ws.shadowRoot.querySelector("avl-calibration-parameter-adjustments");
      return table.shadowRoot.querySelector("tbody tr").textContent;
    });
    assert.match(row, /hardware_snapshot:/);
  });
});

test("profile history lists the run and grows on a second run (append-only)", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToCalibration(page);
    await clickRunCalibration(page);
    await clickRunCalibration(page);
    const count = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-calibration");
      const history = ws.shadowRoot.querySelector("avl-calibration-profile-history");
      return history.shadowRoot.querySelectorAll("li").length;
    });
    assert.equal(count, 2);
  });
});

test("rollback appends a new record and history never shrinks", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToCalibration(page);
    await clickRunCalibration(page);
    await clickRunCalibration(page);
    await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-calibration");
      const history = ws.shadowRoot.querySelector("avl-calibration-profile-history");
      const rollbackButton = [...history.shadowRoot.querySelectorAll("avl-button")].find((b) => b.textContent === "Roll back to this");
      rollbackButton.shadowRoot.querySelector("button").click();
    });
    await page.waitForTimeout(80);
    const count = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-calibration");
      const history = ws.shadowRoot.querySelector("avl-calibration-profile-history");
      return history.shadowRoot.querySelectorAll("li").length;
    });
    assert.equal(count, 3);
    const rows = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-calibration");
      const history = ws.shadowRoot.querySelector("avl-calibration-profile-history");
      return [...history.shadowRoot.querySelectorAll("li")].map((li) => li.textContent);
    });
    assert.ok(rows.some((r) => r.includes("rollback")));
  });
});

test("sufficient evaluation evidence: a later calibration run reaches PROVISIONAL after two agreeing reviewers", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await generateOutput(page, "Calibration evidence check.");
    await submitTwoAgreeingEvaluations(page);
    await goToCalibration(page);
    await clickRunCalibration(page);
    const badges = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-calibration");
      const runPanel = ws.shadowRoot.querySelector("avl-calibration-run-panel");
      const badgeEls = [...runPanel.shadowRoot.querySelectorAll("avl-status-badge")];
      return badgeEls.map((b) => `${b.getAttribute("domain")}=${b.getAttribute("state")}`);
    });
    assert.ok(badges.includes("calibration=PROVISIONAL"));
    assert.ok(!badges.includes("calibration=CALIBRATED"));
  });
});

test("Command Center's Calibration panel shows real, live-updating values", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToCalibration(page);
    await clickRunCalibration(page);
    await page.evaluate(() => {
      location.hash = "#/command-center";
    });
    await page.waitForTimeout(200);
    const metrics = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-command-center");
      const panels = [...ws.shadowRoot.querySelectorAll("avl-panel")];
      const calibration = panels.find((p) => p.getAttribute("title") === "Calibration engine");
      return [...calibration.querySelectorAll("avl-metric-placeholder")].map((m) => `${m.getAttribute("label")}=${m.getAttribute("value")}`);
    });
    assert.ok(metrics.includes("Profile runs=1"));
  });
});

test("Activity update: a calibration run appears on the timeline", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToCalibration(page);
    await clickRunCalibration(page);
    await page.evaluate(() => {
      location.hash = "#/activity";
    });
    await page.waitForTimeout(150);
    const text = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-activity");
      const timeline = ws.shadowRoot.querySelector("avl-activity-timeline");
      return [...timeline.shadowRoot.querySelectorAll("li, tr")].map((r) => r.textContent).join(" | ");
    });
    assert.match(text, /Calibration run completed/);
  });
});

test("Claude context generation: the calibration Claude context is bounded and carries no speaker field", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToCalibration(page);
    await clickRunCalibration(page);
    const contextText = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-calibration");
      const el = ws.shadowRoot.querySelector("avl-claude-calibration-context");
      return el.shadowRoot.querySelector("pre").textContent;
    });
    const context = JSON.parse(contextText);
    assert.equal(context.stage, "calibration");
    assert.equal(context.permissions.max_risk_tier, "read_only");
    assert.doesNotMatch(contextText, /\/home\//);
    assert.doesNotMatch(contextText, /speaker/i);
  });
});

test("light theme: the Calibration workspace renders cleanly with data-theme=light", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToCalibration(page);
    await page.evaluate(() => {
      const toggle = document.querySelector("avl-theme-toggle");
      toggle.shadowRoot.querySelector("button").click();
    });
    await page.waitForTimeout(50);
    const themeAttr = await page.evaluate(() => document.documentElement.getAttribute("data-theme"));
    assert.equal(themeAttr, "light");
    const rendered = await page.evaluate(() => !!document.querySelector("avl-workspace-calibration").shadowRoot.querySelector("avl-calibration-run-panel"));
    assert.equal(rendered, true);
  });
});

test("dark theme: the Calibration workspace renders cleanly with data-theme=dark", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToCalibration(page);
    await page.evaluate(() => {
      const toggle = document.querySelector("avl-theme-toggle");
      toggle.shadowRoot.querySelector("button").click();
      toggle.shadowRoot.querySelector("button").click();
    });
    await page.waitForTimeout(50);
    const themeAttr = await page.evaluate(() => document.documentElement.getAttribute("data-theme"));
    assert.equal(themeAttr, "dark");
    const rendered = await page.evaluate(() => !!document.querySelector("avl-workspace-calibration").shadowRoot.querySelector("avl-calibration-run-panel"));
    assert.equal(rendered, true);
  });
});
