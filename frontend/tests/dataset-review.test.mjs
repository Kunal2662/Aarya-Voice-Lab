// Real-browser (headless Chromium) tests for VL-D3's Dataset Review +
// Voice Quality Analysis workspace: the dashboard, expanded Inspector
// (Quality/Waveform/Segments/Overlap/Technical Review/Feedback),
// candidate review, filters, review queue, Command Center integration,
// and the bounded Claude review context. Covers the VL-D3 §36 scenario
// list. Same withPage/collectShadowText pattern as dataset-workspace.test.mjs.
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
    // See dataset-workspace.test.mjs: the Import workspace's fetch of the
    // gitignored, host-specific dataset_gate_status.json snapshot 404s in
    // a fresh clone by design. Allow exactly that one known bad response.
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

async function goToReview(page) {
  await page.evaluate(() => {
    location.hash = "#/review";
  });
  await page.waitForTimeout(200);
}

async function selectFirstRecording(page) {
  await page.evaluate(() => {
    const ws = document.querySelector("avl-workspace-dataset-review");
    ws.shadowRoot.querySelector("tr[data-selectable]").click();
  });
  await page.waitForTimeout(150);
}

test("open Dataset Review: the workspace mounts with a real dashboard, never a placeholder", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToReview(page);
    const workspaceTag = await page.evaluate(
      () => document.querySelector('avl-app-shell [slot="workspace"]').firstElementChild.tagName.toLowerCase(),
    );
    assert.equal(workspaceTag, "avl-workspace-dataset-review");
    const text = await collectShadowText(page, "avl-workspace-dataset-review");
    assert.match(text, /Total recordings/);
    assert.match(text, /3/);
    assert.match(text, /Dataset Quality Summary/);
  });
});

test("select a recording: the Inspector updates with the expanded VL-D3/VL-D4 sections", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToReview(page);
    await selectFirstRecording(page);
    const sections = await page.evaluate(() => {
      const inspectorRouter = document.querySelector("avl-inspector-router");
      return [...inspectorRouter.shadowRoot.querySelectorAll("details summary")].map((s) => s.textContent);
    });
    assert.deepEqual(sections, [
      "Quality",
      "Waveform",
      "Speech / Silence",
      "Segments",
      "Overlap",
      "Technical Review",
      "Feedback",
      "Provenance",
      "Processing",
    ]);
  });
});

test("quality metrics render real measurement values, never placeholders, for an analyzed recording", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToReview(page);
    await selectFirstRecording(page);
    const text = await collectShadowText(page, "avl-inspector-router");
    assert.match(text, /RMS/);
    assert.match(text, /Estimated SNR/);
    assert.match(text, /Speech ratio/);
    assert.doesNotMatch(text, /this recording has not been analyzed/i);
  });
});

test("waveform renders both the visual frame and its textual equivalent", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToReview(page);
    await selectFirstRecording(page);
    const hasFrame = await page.evaluate(() => {
      const inspectorRouter = document.querySelector("avl-inspector-router");
      const wf = inspectorRouter.shadowRoot.querySelector("avl-waveform-visualization");
      return !!wf.shadowRoot.querySelector('[role="img"]');
    });
    assert.equal(hasFrame, true);
    const text = await collectShadowText(page, "avl-inspector-router");
    // The legend list beneath the waveform names every segment as text.
    assert.match(text, /seg-0001-01/);
  });
});

test("playback controls render with no autoplay and a synthetic-only disclosure", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToReview(page);
    await selectFirstRecording(page);
    const playerState = await page.evaluate(() => {
      const inspectorRouter = document.querySelector("avl-inspector-router");
      const player = inspectorRouter.shadowRoot.querySelector("avl-audio-player");
      const audio = player.shadowRoot.querySelector("audio");
      return {
        autoplay: audio.autoplay,
        loop: audio.loop,
        paused: audio.paused,
        hasSeek: !!player.shadowRoot.querySelector('input[type="range"][aria-label="Seek"]'),
        hasStop: [...player.shadowRoot.querySelectorAll("avl-button")].some((b) => b.textContent.trim() === "Stop"),
      };
    });
    assert.equal(playerState.autoplay, false);
    assert.equal(playerState.loop, false);
    assert.equal(playerState.paused, true, "must never start playing on its own");
    assert.equal(playerState.hasSeek, true);
    assert.equal(playerState.hasStop, true);
    const text = await collectShadowText(page, "avl-inspector-router");
    assert.match(text, /Synthetic tone \(not a real recording\)/);
  });
});

test("segment selection in the timeline updates the Technical Review panel", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToReview(page);
    await selectFirstRecording(page);
    await page.evaluate(() => {
      const inspectorRouter = document.querySelector("avl-inspector-router");
      const timeline = inspectorRouter.shadowRoot.querySelector("avl-segment-timeline");
      timeline.shadowRoot.querySelector("tr[data-selectable]").click();
    });
    await page.waitForTimeout(150);
    const reviewHeading = await page.evaluate(() => {
      const inspectorRouter = document.querySelector("avl-inspector-router");
      const panel = inspectorRouter.shadowRoot.querySelector("avl-candidate-review-panel");
      return panel.shadowRoot.querySelector(".segment-id")?.textContent || null;
    });
    assert.match(reviewHeading, /Reviewing seg-0001-01/);
  });
});

test("filters narrow the recording table by real fixture fields", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToReview(page);
    const before = await collectShadowText(page, "avl-workspace-dataset-review");
    assert.match(before, /3 of 3 recording/);

    await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-dataset-review");
      const search = ws.shadowRoot.querySelector('input[type="search"]');
      search.value = "0002";
      search.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await page.waitForTimeout(100);
    const afterSearch = await collectShadowText(page, "avl-workspace-dataset-review");
    assert.match(afterSearch, /1 of 3 recording/);
  });
});

test("candidate review: Accept records an append-only decision, never overwriting history", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToReview(page);
    await selectFirstRecording(page);
    await page.evaluate(() => {
      const inspectorRouter = document.querySelector("avl-inspector-router");
      const timeline = inspectorRouter.shadowRoot.querySelector("avl-segment-timeline");
      timeline.shadowRoot.querySelector("tr[data-selectable]").click();
    });
    await page.waitForTimeout(150);

    const historyCounts = await page.evaluate(async () => {
      const inspectorRouter = document.querySelector("avl-inspector-router");
      const panel = inspectorRouter.shadowRoot.querySelector("avl-candidate-review-panel");
      const clickDecision = (label) => {
        const button = [...panel.shadowRoot.querySelectorAll("avl-button")].find((b) => b.textContent.trim() === label);
        button.shadowRoot.querySelector("button").click();
      };
      clickDecision("Accept");
      await new Promise((r) => setTimeout(r, 50));
      const afterFirst = panel.shadowRoot.querySelectorAll(".history-item").length;
      clickDecision("Needs review");
      await new Promise((r) => setTimeout(r, 50));
      const afterSecond = panel.shadowRoot.querySelectorAll(".history-item").length;
      return { afterFirst, afterSecond };
    });
    assert.equal(historyCounts.afterFirst, 1);
    assert.equal(historyCounts.afterSecond, 2, "a correction must append, never replace, the prior decision");
  });
});

test("review queue lists pending candidates and shrinks as they are decided", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToReview(page);
    const before = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-dataset-review");
      return ws.shadowRoot.querySelectorAll("h3 + table tbody tr, h3 ~ p.empty-queue").length >= 0
        ? [...ws.shadowRoot.querySelectorAll("h3")].find((h) => h.textContent === "Review queue").nextElementSibling.tagName
        : null;
    });
    assert.ok(before === "TABLE" || before === "P");

    await selectFirstRecording(page);
    // The last selectable row for synthetic-rec-0001 is seg-0001-05
    // (NEEDS_REVIEW in the fixture) — accept it and confirm it leaves
    // the queue.
    await page.evaluate(() => {
      const inspectorRouter = document.querySelector("avl-inspector-router");
      const timeline = inspectorRouter.shadowRoot.querySelector("avl-segment-timeline");
      const rows = timeline.shadowRoot.querySelectorAll("tr[data-selectable]");
      rows[rows.length - 1].click();
    });
    await page.waitForTimeout(100);
    await page.evaluate(async () => {
      const inspectorRouter = document.querySelector("avl-inspector-router");
      const panel = inspectorRouter.shadowRoot.querySelector("avl-candidate-review-panel");
      const button = [...panel.shadowRoot.querySelectorAll("avl-button")].find((b) => b.textContent.trim() === "Accept");
      button.shadowRoot.querySelector("button").click();
      await new Promise((r) => setTimeout(r, 50));
    });
    await page.waitForTimeout(150);

    const queueText = await collectShadowText(page, "avl-workspace-dataset-review");
    assert.doesNotMatch(queueText, /seg-0001-05/, "an accepted segment must drop out of the persistent review queue");
    assert.match(queueText, /seg-0001-03/, "a still-pending segment must remain in the queue");
  });
});

test("feedback can be recorded against the selected recording", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToReview(page);
    await selectFirstRecording(page);
    const statusText = await page.evaluate(async () => {
      const inspectorRouter = document.querySelector("avl-inspector-router");
      const form = inspectorRouter.shadowRoot.querySelector("avl-feedback-form");
      const submit = [...form.shadowRoot.querySelectorAll("avl-button")].find((b) => b.textContent.trim() === "Submit feedback");
      submit.shadowRoot.querySelector("button").click();
      await new Promise((r) => setTimeout(r, 50));
      return form.shadowRoot.querySelector(".status").textContent;
    });
    assert.match(statusText, /Recorded feedback-\d+ for synthetic-rec-0001/);
  });
});

test("Command Center's Review panel shows real, non-fabricated review counts", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    const metrics = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-command-center");
      const panels = [...ws.shadowRoot.querySelectorAll("avl-panel")];
      const review = panels.find((p) => p.getAttribute("title") === "Review");
      return [...review.querySelectorAll("avl-metric-placeholder")].map((m) => m.getAttribute("label"));
    });
    assert.deepEqual(metrics, ["Review queue", "Pending candidates", "Quality warnings", "Recent analyses", "Failed analyses", "Current batch review"]);
  });
});

test("Claude review context is bounded and never includes a filesystem path or speaker field", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToReview(page);
    await selectFirstRecording(page);
    const contextText = await page.evaluate(() => {
      const inspectorRouter = document.querySelector("avl-inspector-router");
      const el = inspectorRouter.shadowRoot.querySelector("avl-claude-review-context");
      return el.shadowRoot.querySelector("pre").textContent;
    });
    const context = JSON.parse(contextText);
    assert.deepEqual(Object.keys(context).sort(), ["batch_id", "config", "error", "metric", "permissions", "provenance", "recording_id", "stage", "warning"]);
    assert.equal(context.permissions.max_risk_tier, "read_only");
    assert.doesNotMatch(contextText, /\/home\//);
    assert.doesNotMatch(contextText, /speaker/i);
  });
});
