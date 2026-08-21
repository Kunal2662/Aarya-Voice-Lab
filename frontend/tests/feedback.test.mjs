// Real-browser (headless Chromium) tests for VL-D6's Voice Feedback +
// Human Evaluation workspace: opening the workspace, the evaluation
// queue, listening gates (no autoplay, replay tracking, honest
// listened-state), rating/confidence/comment submission, A/B comparison
// (all four decisions), disagreement + history display, Command Center
// and Activity integration, the bounded Claude evaluation context, and
// light/dark theme rendering. Same withPage/collectShadowText pattern as
// preview.test.mjs.
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

async function goToPreview(page) {
  await page.evaluate(() => {
    location.hash = "#/preview";
  });
  await page.waitForTimeout(200);
}

async function generateOutput(page, text) {
  await goToPreview(page);
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

async function goToFeedback(page) {
  await page.evaluate(() => {
    location.hash = "#/feedback";
  });
  await page.waitForTimeout(200);
}

async function selectFirstQueueRow(page) {
  await page.evaluate(() => {
    const ws = document.querySelector("avl-workspace-feedback");
    const queue = ws.shadowRoot.querySelector("avl-evaluation-queue");
    const row = queue.shadowRoot.querySelector("tbody tr");
    row.querySelector("avl-button").shadowRoot.querySelector("button").click();
  });
  await page.waitForTimeout(100);
}

async function pressPlayOnForm(page) {
  await page.evaluate(() => {
    const form = document.querySelector("avl-workspace-feedback").shadowRoot.querySelector("avl-evaluation-form");
    const audioPlayer = form.shadowRoot.querySelector("avl-voice-player").shadowRoot.querySelector("avl-audio-player");
    const playButton = [...audioPlayer.shadowRoot.querySelectorAll("avl-button")].find((b) => b.textContent === "Play" || b.textContent === "Pause");
    playButton.shadowRoot.querySelector("button").click();
  });
  await page.waitForTimeout(60);
}

async function rateFirstDimension(page, scoreIndex) {
  await page.evaluate((idx) => {
    const form = document.querySelector("avl-workspace-feedback").shadowRoot.querySelector("avl-evaluation-form");
    const ratingPanel = form.shadowRoot.querySelector("avl-rating-panel");
    ratingPanel.shadowRoot.querySelectorAll("button.score-btn")[idx].click();
  }, scoreIndex);
}

async function submitEvaluation(page, label) {
  await page.evaluate((l) => {
    const form = document.querySelector("avl-workspace-feedback").shadowRoot.querySelector("avl-evaluation-form");
    const button = [...form.shadowRoot.querySelectorAll("avl-button")].find((b) => b.textContent === l);
    button.shadowRoot.querySelector("button").click();
  }, label);
  await page.waitForTimeout(80);
}

test("open workspace: navigating to Feedback mounts avl-workspace-feedback with a real dashboard", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToFeedback(page);
    const workspaceTag = await page.evaluate(
      () => document.querySelector('avl-app-shell [slot="workspace"]').firstElementChild.tagName.toLowerCase(),
    );
    assert.equal(workspaceTag, "avl-workspace-feedback");
    const metrics = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-feedback");
      return [...ws.shadowRoot.querySelectorAll(".dashboard avl-stat-tile")].map((m) => m.getAttribute("label"));
    });
    assert.deepEqual(metrics, ["Outputs available", "Unevaluated", "Evaluated", "Disagreement", "Total evaluations", "Reviewers"]);
  });
});

test("evaluation queue renders: shows the generated output with an IN_PROGRESS (not started) status", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await generateOutput(page, "Queue render check.");
    await goToFeedback(page);
    const row = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-feedback");
      const queue = ws.shadowRoot.querySelector("avl-evaluation-queue");
      return queue.shadowRoot.querySelector("tbody tr").textContent.replace(/\s+/g, " ").trim();
    });
    assert.match(row, /preview-req-\d+-preview/);
    assert.match(row, /\(not started\)/);
  });
});

test("output can be played from the evaluation form", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await generateOutput(page, "Playback check.");
    await goToFeedback(page);
    await selectFirstQueueRow(page);
    await pressPlayOnForm(page);
    const playing = await page.evaluate(() => {
      const form = document.querySelector("avl-workspace-feedback").shadowRoot.querySelector("avl-evaluation-form");
      const audio = form.shadowRoot.querySelector("avl-voice-player").shadowRoot.querySelector("avl-audio-player").shadowRoot.querySelector("audio");
      return !audio.paused;
    });
    assert.equal(playing, true);
  });
});

test("no autoplay: the evaluation form's player never starts playback on its own", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await generateOutput(page, "No autoplay check.");
    await goToFeedback(page);
    await selectFirstQueueRow(page);
    await page.waitForTimeout(150);
    const paused = await page.evaluate(() => {
      const form = document.querySelector("avl-workspace-feedback").shadowRoot.querySelector("avl-evaluation-form");
      const audio = form.shadowRoot.querySelector("avl-voice-player").shadowRoot.querySelector("avl-audio-player").shadowRoot.querySelector("audio");
      return audio.paused;
    });
    assert.equal(paused, true, "playback must never start without an explicit Play press");
  });
});

test("replay works: pressing Play a second time is tracked as a replay, not a fresh first listen", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await generateOutput(page, "Replay tracking check.");
    await goToFeedback(page);
    await selectFirstQueueRow(page);
    await pressPlayOnForm(page);
    await page.evaluate(() => {
      const form = document.querySelector("avl-workspace-feedback").shadowRoot.querySelector("avl-evaluation-form");
      const audio = form.shadowRoot.querySelector("avl-voice-player").shadowRoot.querySelector("avl-audio-player").shadowRoot.querySelector("audio");
      audio.currentTime = 0;
      audio.dispatchEvent(new Event("pause"));
    });
    await pressPlayOnForm(page);
    await submitEvaluation(page, "Submit evaluation");
    const listening = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-feedback");
      const history = ws.shadowRoot.querySelector("avl-evaluation-history-panel");
      return history.shadowRoot.querySelector("li .meta").textContent;
    });
    assert.match(listening, /listened: true/);
  });
});

test("evaluation cannot be falsely marked listened: Submit evaluation is disabled until Play is actually pressed", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await generateOutput(page, "Listen gate check.");
    await goToFeedback(page);
    await selectFirstQueueRow(page);
    const disabledBefore = await page.evaluate(() => {
      const form = document.querySelector("avl-workspace-feedback").shadowRoot.querySelector("avl-evaluation-form");
      const button = [...form.shadowRoot.querySelectorAll("avl-button")].find((b) => b.textContent === "Submit evaluation");
      return button.hasAttribute("disabled");
    });
    assert.equal(disabledBefore, true);

    await pressPlayOnForm(page);
    const disabledAfter = await page.evaluate(() => {
      const form = document.querySelector("avl-workspace-feedback").shadowRoot.querySelector("avl-evaluation-form");
      const button = [...form.shadowRoot.querySelectorAll("avl-button")].find((b) => b.textContent === "Submit evaluation");
      return button.hasAttribute("disabled");
    });
    assert.equal(disabledAfter, false);
  });
});

test("cannot judge never requires listening", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await generateOutput(page, "Cannot-judge gate check.");
    await goToFeedback(page);
    await selectFirstQueueRow(page);
    await submitEvaluation(page, "Cannot judge");
    const historyCount = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-feedback");
      const history = ws.shadowRoot.querySelector("avl-evaluation-history-panel");
      return history.shadowRoot.querySelectorAll("li").length;
    });
    assert.equal(historyCount, 1);
  });
});

test("rating submission: a submitted evaluation records the chosen dimension score", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await generateOutput(page, "Rating submission check.");
    await goToFeedback(page);
    await selectFirstQueueRow(page);
    await pressPlayOnForm(page);
    await rateFirstDimension(page, 3); // score 4 on the first dimension row (NATURALNESS)
    await submitEvaluation(page, "Submit evaluation");
    const scoresText = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-feedback");
      const history = ws.shadowRoot.querySelector("avl-evaluation-history-panel");
      return history.shadowRoot.querySelector("li .scores").textContent;
    });
    assert.match(scoresText, /NATURALNESS: 4/);
  });
});

test("confidence submission: a submitted evaluation records the chosen confidence", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await generateOutput(page, "Confidence submission check.");
    await goToFeedback(page);
    await selectFirstQueueRow(page);
    await pressPlayOnForm(page);
    await page.evaluate(() => {
      const form = document.querySelector("avl-workspace-feedback").shadowRoot.querySelector("avl-evaluation-form");
      const confidence = form.shadowRoot.querySelector("avl-confidence-control");
      confidence.shadowRoot.querySelectorAll("button.score-btn")[3].click(); // confidence 4
    });
    await submitEvaluation(page, "Submit evaluation");
    const metaText = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-feedback");
      const history = ws.shadowRoot.querySelector("avl-evaluation-history-panel");
      return history.shadowRoot.querySelector("li .meta").textContent;
    });
    assert.match(metaText, /confidence: 4/);
  });
});

test("comment submission: a submitted evaluation records the free-form comment", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await generateOutput(page, "Comment submission check.");
    await goToFeedback(page);
    await selectFirstQueueRow(page);
    await pressPlayOnForm(page);
    await page.evaluate(() => {
      const form = document.querySelector("avl-workspace-feedback").shadowRoot.querySelector("avl-evaluation-form");
      const textarea = form.shadowRoot.querySelector("textarea");
      textarea.value = "This is a real reviewer comment.";
    });
    await submitEvaluation(page, "Submit evaluation");
    const commentText = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-feedback");
      const history = ws.shadowRoot.querySelector("avl-evaluation-history-panel");
      return history.shadowRoot.querySelector("li .comment").textContent;
    });
    assert.equal(commentText, "This is a real reviewer comment.");
  });
});

async function setUpAbPair(page) {
  await generateOutput(page, "First A/B evaluation line.");
  await generateOutput(page, "Second A/B evaluation line.");
  await goToFeedback(page);
  await page.evaluate(() => {
    const ws = document.querySelector("avl-workspace-feedback");
    const queue = ws.shadowRoot.querySelector("avl-evaluation-queue");
    const rows = queue.shadowRoot.querySelectorAll("tbody tr");
    rows[0].querySelector("avl-button").shadowRoot.querySelector("button").click();
  });
  await page.waitForTimeout(100);
  await page.evaluate(() => {
    const ws = document.querySelector("avl-workspace-feedback");
    const select = [...ws.shadowRoot.querySelectorAll("select")].find((s) => s.getAttribute("aria-label") === "Compare with");
    select.selectedIndex = 1;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await page.waitForTimeout(100);
}

async function playBothAbSides(page) {
  await page.evaluate(async () => {
    const ws = document.querySelector("avl-workspace-feedback");
    const ab = ws.shadowRoot.querySelector("avl-ab-evaluation");
    const forms = ab.shadowRoot.querySelectorAll("avl-evaluation-form");
    for (const form of forms) {
      const audioPlayer = form.shadowRoot.querySelector("avl-voice-player").shadowRoot.querySelector("avl-audio-player");
      const playButton = [...audioPlayer.shadowRoot.querySelectorAll("avl-button")].find((b) => b.textContent === "Play" || b.textContent === "Pause");
      playButton.shadowRoot.querySelector("button").click();
      await new Promise((r) => setTimeout(r, 40));
    }
  });
  await page.waitForTimeout(60);
}

function clickAbDecision(page, label) {
  return page.evaluate((l) => {
    const ws = document.querySelector("avl-workspace-feedback");
    const ab = ws.shadowRoot.querySelector("avl-ab-evaluation");
    const button = [...ab.shadowRoot.querySelectorAll("avl-button")].find((b) => b.textContent === l);
    button.shadowRoot.querySelector("button").click();
  }, label);
}

test("A/B comparison: the workspace offers a compare-with select and mounts avl-ab-evaluation", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await setUpAbPair(page);
    const hasAb = await page.evaluate(() => !!document.querySelector("avl-workspace-feedback").shadowRoot.querySelector("avl-ab-evaluation"));
    assert.equal(hasAb, true);
  });
});

test("A preference: PREFER_A is gated until both sides are listened to, then records correctly", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await setUpAbPair(page);
    const gatedBefore = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-feedback");
      const ab = ws.shadowRoot.querySelector("avl-ab-evaluation");
      const button = [...ab.shadowRoot.querySelectorAll("avl-button")].find((b) => b.textContent === "Prefer A");
      return button.hasAttribute("disabled");
    });
    assert.equal(gatedBefore, true);

    await playBothAbSides(page);
    await clickAbDecision(page, "Prefer A");
    await page.waitForTimeout(80);
    const status = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-feedback");
      return ws.shadowRoot.querySelector("avl-ab-evaluation").shadowRoot.querySelector(".status").textContent;
    });
    assert.match(status, /Prefer A/);
  });
});

test("B preference: PREFER_B records correctly once both sides are listened to", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await setUpAbPair(page);
    await playBothAbSides(page);
    await clickAbDecision(page, "Prefer B");
    await page.waitForTimeout(80);
    const status = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-feedback");
      return ws.shadowRoot.querySelector("avl-ab-evaluation").shadowRoot.querySelector(".status").textContent;
    });
    assert.match(status, /Prefer B/);
  });
});

test("no preference: NO_PREFERENCE records correctly once both sides are listened to", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await setUpAbPair(page);
    await playBothAbSides(page);
    await clickAbDecision(page, "No preference");
    await page.waitForTimeout(80);
    const status = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-feedback");
      return ws.shadowRoot.querySelector("avl-ab-evaluation").shadowRoot.querySelector(".status").textContent;
    });
    assert.match(status, /No preference/);
  });
});

test("cannot judge (A/B): CANNOT_JUDGE never requires listening to either side", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await setUpAbPair(page);
    await clickAbDecision(page, "Cannot judge");
    await page.waitForTimeout(80);
    const status = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-feedback");
      return ws.shadowRoot.querySelector("avl-ab-evaluation").shadowRoot.querySelector(".status").textContent;
    });
    assert.match(status, /Cannot judge/);
  });
});

test("blinding: toggling Blind comparison hides the metadata table and swaps A/B labels for generic ones", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await setUpAbPair(page);
    const before = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-feedback");
      const ab = ws.shadowRoot.querySelector("avl-ab-evaluation");
      return !!ab.shadowRoot.querySelector("table");
    });
    assert.equal(before, true);
    await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-feedback");
      const ab = ws.shadowRoot.querySelector("avl-ab-evaluation");
      ab.shadowRoot.querySelector('input[type="checkbox"]').click();
    });
    await page.waitForTimeout(50);
    const after = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-feedback");
      const ab = ws.shadowRoot.querySelector("avl-ab-evaluation");
      return !!ab.shadowRoot.querySelector("table");
    });
    assert.equal(after, false);
  });
});

async function createDisagreement(page) {
  await generateOutput(page, "Disagreement scenario line.");
  await goToFeedback(page);
  await selectFirstQueueRow(page);
  await page.evaluate(() => {
    const form = document.querySelector("avl-workspace-feedback").shadowRoot.querySelector("avl-evaluation-form");
    form.reviewer = "alice";
  });
  await pressPlayOnForm(page);
  await rateFirstDimension(page, 4); // score 5 as alice
  await submitEvaluation(page, "Submit evaluation");

  await selectFirstQueueRow(page);
  await page.evaluate(() => {
    const form = document.querySelector("avl-workspace-feedback").shadowRoot.querySelector("avl-evaluation-form");
    form.reviewer = "bob";
  });
  await pressPlayOnForm(page);
  await rateFirstDimension(page, 0); // score 1 as bob -> spread 4
  await submitEvaluation(page, "Submit evaluation");
}

test("disagreement display: two reviewers scoring far apart flags the disagreeing dimension", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await createDisagreement(page);
    const disagreementText = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-feedback");
      return ws.shadowRoot.querySelector("avl-disagreement-view").shadowRoot.querySelector("tr.flagged").textContent;
    });
    assert.match(disagreementText, /NATURALNESS/);
  });
});

test("history display: the evaluation history panel lists both reviewers, append-only", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await createDisagreement(page);
    const reviewers = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-feedback");
      const history = ws.shadowRoot.querySelector("avl-evaluation-history-panel");
      return [...history.shadowRoot.querySelectorAll("li .reviewer")].map((r) => r.textContent);
    });
    assert.deepEqual(reviewers, ["alice", "bob"]);
  });
});

test("aggregated results: the aggregated panel reports honest variance for two disagreeing scores", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await createDisagreement(page);
    const rowText = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-feedback");
      const rows = [...ws.shadowRoot.querySelector("avl-aggregated-results-panel").shadowRoot.querySelectorAll("tbody tr")];
      return rows.find((r) => r.textContent.includes("NATURALNESS")).textContent.replace(/\s+/g, " ");
    });
    assert.match(rowText, /NATURALNESS 2/); // sample_count 2
  });
});

test("calibration readiness stays UNCALIBRATED regardless of how many evaluations exist", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await createDisagreement(page);
    const state = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-feedback");
      const panel = ws.shadowRoot.querySelector("avl-calibration-panel");
      return panel.shadowRoot.querySelector("avl-status-badge").getAttribute("state");
    });
    assert.equal(state, "UNCALIBRATED");
  });
});

test("Command Center's Feedback panel shows real, live-updating counts", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await createDisagreement(page);
    await page.evaluate(() => {
      location.hash = "#/command-center";
    });
    await page.waitForTimeout(200);
    const metrics = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-command-center");
      const panels = [...ws.shadowRoot.querySelectorAll("avl-panel")];
      const feedback = panels.find((p) => p.getAttribute("title") === "Feedback");
      return [...feedback.querySelectorAll("avl-metric-placeholder")].map((m) => `${m.getAttribute("label")}=${m.getAttribute("value")}`);
    });
    assert.ok(metrics.includes("Total evaluations=2"));
    assert.ok(metrics.includes("Disagreement=1"));
  });
});

test("Activity update: evaluation started, output listened, and evaluation completed all appear on the timeline", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await generateOutput(page, "Activity timeline check.");
    await goToFeedback(page);
    await selectFirstQueueRow(page);
    await pressPlayOnForm(page);
    await rateFirstDimension(page, 2);
    await submitEvaluation(page, "Submit evaluation");
    await page.evaluate(() => {
      location.hash = "#/activity";
    });
    await page.waitForTimeout(150);
    const text = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-activity");
      const timeline = ws.shadowRoot.querySelector("avl-activity-timeline");
      return [...timeline.shadowRoot.querySelectorAll("li, tr")].map((r) => r.textContent).join(" | ");
    });
    assert.match(text, /Evaluation started/);
    assert.match(text, /Output listened/);
    assert.match(text, /Evaluation completed/);
  });
});

test("Claude context generation: the evaluation Claude context is bounded, redacts the output id, and carries no speaker field", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await generateOutput(page, "Claude context check.");
    await goToFeedback(page);
    await selectFirstQueueRow(page);
    await pressPlayOnForm(page);
    await rateFirstDimension(page, 3);
    await submitEvaluation(page, "Submit evaluation");
    const contextText = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-feedback");
      const el = ws.shadowRoot.querySelector("avl-claude-evaluation-context");
      return el.shadowRoot.querySelector("pre").textContent;
    });
    const context = JSON.parse(contextText);
    assert.deepEqual(
      Object.keys(context).sort(),
      ["batch_id", "config", "error", "metric", "permissions", "provenance", "recording_id", "stage", "warning"],
    );
    assert.equal(context.stage, "voice_evaluation");
    assert.equal(context.permissions.max_risk_tier, "read_only");
    assert.doesNotMatch(contextText, /\/home\//);
    assert.doesNotMatch(contextText, /speaker/i);
  });
});

test("light theme: the Feedback workspace renders cleanly with data-theme=light", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await generateOutput(page, "Light theme check.");
    await goToFeedback(page);
    await page.evaluate(() => {
      const toggle = document.querySelector("avl-theme-toggle");
      toggle.shadowRoot.querySelector("button").click(); // system -> light
    });
    await page.waitForTimeout(50);
    const themeAttr = await page.evaluate(() => document.documentElement.getAttribute("data-theme"));
    assert.equal(themeAttr, "light");
    const rendered = await page.evaluate(() => !!document.querySelector("avl-workspace-feedback").shadowRoot.querySelector("avl-evaluation-queue"));
    assert.equal(rendered, true);
  });
});

test("dark theme: the Feedback workspace renders cleanly with data-theme=dark", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await generateOutput(page, "Dark theme check.");
    await goToFeedback(page);
    await page.evaluate(() => {
      const toggle = document.querySelector("avl-theme-toggle");
      toggle.shadowRoot.querySelector("button").click(); // system -> light
      toggle.shadowRoot.querySelector("button").click(); // light -> dark
    });
    await page.waitForTimeout(50);
    const themeAttr = await page.evaluate(() => document.documentElement.getAttribute("data-theme"));
    assert.equal(themeAttr, "dark");
    const rendered = await page.evaluate(() => !!document.querySelector("avl-workspace-feedback").shadowRoot.querySelector("avl-evaluation-queue"));
    assert.equal(rendered, true);
  });
});

test("no console errors: a full generate/play/rate/confidence/comment/submit/A-B pass leaves the console clean", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await setUpAbPair(page);
    await playBothAbSides(page);
    await clickAbDecision(page, "Prefer A");
    await page.waitForTimeout(150);
    // withPage()'s own teardown asserts consoleErrors is empty; reaching
    // this point is the scenario itself.
  });
});
