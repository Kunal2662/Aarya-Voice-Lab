// Real-browser (headless Chromium) tests for VL-D5's Voice Preview +
// Generation workspace: text input, generation settings, the queue,
// generated outputs, playback, waveform, A/B comparison, feedback,
// regeneration, provenance, history, Command Center integration, the
// bounded Claude generation context, and the honest unavailable-backend
// state. Covers the VL-D5 §36 scenario list (19 scenarios). Same
// withPage/collectShadowText pattern as processing.test.mjs.
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

async function enterText(page, text) {
  await page.evaluate((text) => {
    const ws = document.querySelector("avl-workspace-preview");
    const textarea = ws.shadowRoot.querySelector("avl-text-input").shadowRoot.querySelector("textarea");
    textarea.value = text;
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  }, text);
}

async function selectModel(page, modelId) {
  await page.evaluate((modelId) => {
    const ws = document.querySelector("avl-workspace-preview");
    const settings = ws.shadowRoot.querySelector("avl-generation-settings");
    const select = settings.shadowRoot.querySelector('select[aria-label="Generation model"]');
    select.value = modelId;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  }, modelId);
}

async function clickGenerate(page) {
  await page.evaluate(() => {
    const ws = document.querySelector("avl-workspace-preview");
    const button = [...ws.shadowRoot.querySelectorAll("avl-button")].find((b) => b.textContent.trim() === "Generate preview");
    button.shadowRoot.querySelector("button").click();
  });
  await page.waitForTimeout(1200);
}

test("open workspace: navigating to Preview mounts avl-workspace-preview with a real dashboard", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToPreview(page);
    const workspaceTag = await page.evaluate(
      () => document.querySelector('avl-app-shell [slot="workspace"]').firstElementChild.tagName.toLowerCase(),
    );
    assert.equal(workspaceTag, "avl-workspace-preview");
    const metrics = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-preview");
      return [...ws.shadowRoot.querySelectorAll(".metric .label")].map((m) => m.textContent);
    });
    assert.deepEqual(metrics, ["Total requested", "Queued", "Generating", "Ready", "Warning", "Failed", "Blocked", "Cancelled", "Avg duration"]);
  });
});

test("enter text: the text input shows real character/word counts and a heuristic duration estimate", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToPreview(page);
    await enterText(page, "one two three four five");
    const counts = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-preview");
      const input = ws.shadowRoot.querySelector("avl-text-input");
      return [...input.shadowRoot.querySelectorAll(".counts span")].map((s) => s.textContent);
    });
    assert.match(counts[0], /23 \/ \d+ characters/);
    assert.match(counts[1], /5 word\(s\)/);
  });
});

test("select voice profile: the default profile exists and is selectable in Generation Settings", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToPreview(page);
    const options = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-preview");
      const settings = ws.shadowRoot.querySelector("avl-generation-settings");
      const select = settings.shadowRoot.querySelector('select[aria-label="Voice profile"]');
      return [...select.options].map((o) => o.textContent);
    });
    assert.match(options[0], /demo-voice/);
  });
});

test("select backend: the model select offers the synthetic-tone and unavailable-backend fixtures", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToPreview(page);
    const options = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-preview");
      const settings = ws.shadowRoot.querySelector("avl-generation-settings");
      const select = settings.shadowRoot.querySelector('select[aria-label="Generation model"]');
      return [...select.options].map((o) => o.textContent);
    });
    assert.ok(options.some((o) => /Synthetic Tone.*AVAILABLE/.test(o)));
    assert.ok(options.some((o) => /Unavailable Backend.*UNAVAILABLE/.test(o)));
  });
});

test("generate: clicking Generate preview creates a real queue item and a completed output", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToPreview(page);
    await enterText(page, "Hello from the Playwright suite.");
    await clickGenerate(page);
    const outcome = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-preview");
      const queueRows = ws.shadowRoot.querySelector("avl-generation-queue").shadowRoot.querySelectorAll("tbody tr").length;
      const cards = ws.shadowRoot.querySelectorAll("avl-voice-preview-card").length;
      return { queueRows, cards };
    });
    assert.equal(outcome.queueRows, 1);
    assert.equal(outcome.cards, 1);
  });
});

test("show queue: the generation queue table reports the real request text and status", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToPreview(page);
    await enterText(page, "Queue visibility check.");
    await clickGenerate(page);
    const row = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-preview");
      const queueEl = ws.shadowRoot.querySelector("avl-generation-queue");
      return queueEl.shadowRoot.querySelector("tbody tr").textContent.replace(/\s+/g, " ").trim();
    });
    assert.match(row, /Queue visibility check\./);
    assert.match(row, /demo-voice-v1/);
  });
});

test("show completed output: a READY generation renders a preview card with the SYNTHETIC_FIXTURE kind", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToPreview(page);
    await enterText(page, "Completed output check.");
    await clickGenerate(page);
    const cardText = await page.evaluate(() => {
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
      const ws = document.querySelector("avl-workspace-preview");
      const card = ws.shadowRoot.querySelector("avl-voice-preview-card");
      return collect(card.shadowRoot);
    });
    assert.match(cardText, /synthetic fixture/);
    assert.match(cardText, /synthetic/);
  });
});

test("play: pressing Play on a generated output's player starts playback with no console error", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToPreview(page);
    await enterText(page, "Playback check.");
    await clickGenerate(page);
    const playing = await page.evaluate(async () => {
      const ws = document.querySelector("avl-workspace-preview");
      const card = ws.shadowRoot.querySelector("avl-voice-preview-card");
      const audioPlayer = card.shadowRoot.querySelector("avl-voice-player").shadowRoot.querySelector("avl-audio-player");
      const playBtn = audioPlayer.shadowRoot.querySelectorAll("avl-button")[0];
      playBtn.shadowRoot.querySelector("button").click();
      await new Promise((r) => setTimeout(r, 150));
      const audioEl = audioPlayer.shadowRoot.querySelector("audio");
      return !audioEl.paused;
    });
    assert.equal(playing, true);
  });
});

test("seek: the audio player exposes a seek control and volume/speed controls", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToPreview(page);
    await enterText(page, "Seek control check.");
    await clickGenerate(page);
    const controls = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-preview");
      const card = ws.shadowRoot.querySelector("avl-voice-preview-card");
      const audioPlayer = card.shadowRoot.querySelector("avl-voice-player").shadowRoot.querySelector("avl-audio-player");
      return {
        hasSeek: !!audioPlayer.shadowRoot.querySelector('input[aria-label="Seek"]'),
        hasVolume: !!audioPlayer.shadowRoot.querySelector('input[aria-label="Volume"]'),
        hasSpeed: !!audioPlayer.shadowRoot.querySelector('select[aria-label="Playback speed"]'),
      };
    });
    assert.deepEqual(controls, { hasSeek: true, hasVolume: true, hasSpeed: true });
  });
});

test("waveform: a generated output's player renders the waveform visualisation", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToPreview(page);
    await enterText(page, "Waveform render check.");
    await clickGenerate(page);
    const hasWaveform = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-preview");
      const card = ws.shadowRoot.querySelector("avl-voice-preview-card");
      return !!card.shadowRoot.querySelector("avl-voice-player").shadowRoot.querySelector("avl-waveform-visualization");
    });
    assert.equal(hasWaveform, true);
  });
});

test("A/B comparison: two completed outputs can be compared with metadata only, no similarity claim", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToPreview(page);
    await enterText(page, "First A/B line.");
    await clickGenerate(page);
    await enterText(page, "Second A/B line.");
    await clickGenerate(page);
    const abText = await page.evaluate(async () => {
      const ws = document.querySelector("avl-workspace-preview");
      const select = [...ws.shadowRoot.querySelectorAll("select")].find((s) => s.getAttribute("aria-label") === "Compare with");
      select.selectedIndex = 1;
      select.dispatchEvent(new Event("change", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 50));
      const ab = ws.shadowRoot.querySelector("avl-ab-comparison");
      return ab ? ab.shadowRoot.textContent : null;
    });
    assert.ok(abText);
    assert.match(abText, /no acoustic similarity claim is made/);
  });
});

test("feedback: Uncertain can be recorded without listening, Accept is gated until Play is pressed", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToPreview(page);
    await enterText(page, "Feedback gating check.");
    await clickGenerate(page);
    const before = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-preview");
      const form = ws.shadowRoot.querySelector("avl-preview-feedback-form");
      const accept = [...form.shadowRoot.querySelectorAll("avl-button")].find((b) => b.textContent.trim() === "Accept");
      return accept.hasAttribute("disabled");
    });
    assert.equal(before, true, "Accept must be gated before listening");

    const status = await page.evaluate(async () => {
      const ws = document.querySelector("avl-workspace-preview");
      const form = ws.shadowRoot.querySelector("avl-preview-feedback-form");
      const uncertain = [...form.shadowRoot.querySelectorAll("avl-button")].find((b) => b.textContent.trim() === "Uncertain");
      uncertain.shadowRoot.querySelector("button").click();
      await new Promise((r) => setTimeout(r, 50));
      return form.shadowRoot.querySelector(".status").textContent;
    });
    assert.match(status, /Recorded preview-feedback-\d+ \(Uncertain\)/);
  });
});

test("regenerate: a second generation for the same voice profile appears as Generation 2 in history", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToPreview(page);
    await enterText(page, "First generation.");
    await clickGenerate(page);
    await enterText(page, "Second generation (regenerate).");
    await clickGenerate(page);

    await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-preview");
      ws.shadowRoot.querySelector("table tr[data-selectable]").click();
    });
    await page.waitForTimeout(200);

    const labels = await page.evaluate(() => {
      const inspectorRouter = document.querySelector("avl-inspector-router");
      const panel = inspectorRouter.shadowRoot.querySelector("avl-generation-history-panel");
      return [...panel.shadowRoot.querySelectorAll("li")].map((li) => li.textContent.replace(/\s+/g, " ").trim());
    });
    assert.equal(labels.length, 2);
    assert.match(labels[0], /Generation 1/);
    assert.match(labels[1], /Generation 2/);
  });
});

test("inspect provenance: the workspace's Provenance section reports request/output/config identity", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToPreview(page);
    await enterText(page, "Provenance check.");
    await clickGenerate(page);
    const text = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-preview");
      const rows = [...ws.shadowRoot.querySelectorAll(".rows")].find((r) => r.textContent.includes("Request ID"));
      return rows.textContent.replace(/\s+/g, " ");
    });
    assert.match(text, /Request ID/);
    assert.match(text, /Output ID/);
    assert.match(text, /Config hash/);
    assert.match(text, /Output SHA-256/);
    assert.match(text, /Artifact ID/);
  });
});

test("view history: selecting a voice profile reveals its generation history in the Inspector", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToPreview(page);
    await enterText(page, "History view check.");
    await clickGenerate(page);
    await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-preview");
      ws.shadowRoot.querySelector("table tr[data-selectable]").click();
    });
    await page.waitForTimeout(200);
    const historyCount = await page.evaluate(() => {
      const inspectorRouter = document.querySelector("avl-inspector-router");
      const panel = inspectorRouter.shadowRoot.querySelector("avl-generation-history-panel");
      return panel.shadowRoot.querySelectorAll("li").length;
    });
    assert.equal(historyCount, 1);
  });
});

test("Command Center's Preview panel shows real, live-updating counts", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToPreview(page);
    await enterText(page, "Command Center check.");
    await clickGenerate(page);
    await page.evaluate(() => {
      location.hash = "#/command-center";
    });
    await page.waitForTimeout(200);
    const metrics = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-command-center");
      const panels = [...ws.shadowRoot.querySelectorAll("avl-panel")];
      const preview = panels.find((p) => p.getAttribute("title") === "Preview");
      return [...preview.querySelectorAll("avl-metric-placeholder")].map((m) => `${m.getAttribute("label")}=${m.getAttribute("value")}`);
    });
    assert.ok(metrics.includes("Total generated=1"));
    assert.ok(metrics.includes("Ready=1"));
  });
});

test("Claude generation context is bounded and never includes a filesystem path, speaker field, or raw preview text", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToPreview(page);
    await enterText(page, "This exact sentence must never leak into the Claude context.");
    await clickGenerate(page);
    await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-preview");
      ws.shadowRoot.querySelector("table tr[data-selectable]").click();
    });
    await page.waitForTimeout(200);
    const contextText = await page.evaluate(() => {
      const inspectorRouter = document.querySelector("avl-inspector-router");
      const el = inspectorRouter.shadowRoot.querySelector("avl-claude-generation-context");
      return el.shadowRoot.querySelector("pre").textContent;
    });
    const context = JSON.parse(contextText);
    assert.deepEqual(
      Object.keys(context).sort(),
      ["batch_id", "config", "error", "metric", "permissions", "provenance", "recording_id", "stage", "warning"],
    );
    assert.equal(context.stage, "voice_generation");
    assert.equal(context.permissions.max_risk_tier, "read_only");
    assert.doesNotMatch(contextText, /\/home\//);
    assert.doesNotMatch(contextText, /speaker/i);
    assert.doesNotMatch(contextText, /This exact sentence must never leak/);
  });
});

test("honest unavailable-backend state: selecting the unavailable backend blocks generation, never a fabricated success", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToPreview(page);
    await enterText(page, "This should be blocked.");
    await selectModel(page, "unavailable-model-v1");
    await clickGenerate(page);
    const status = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-preview");
      const queueEl = ws.shadowRoot.querySelector("avl-generation-queue");
      const badge = queueEl.shadowRoot.querySelector("avl-status-badge");
      return badge.getAttribute("state");
    });
    assert.equal(status, "BLOCKED");

    const settingsControls = await page.evaluate(() => {
      const ws = document.querySelector("avl-workspace-preview");
      const settings = ws.shadowRoot.querySelector("avl-generation-settings");
      return [...settings.shadowRoot.querySelectorAll("label")]
        .map((l) => l.textContent.trim())
        .filter((t) => /NOT AVAILABLE/.test(t));
    });
    assert.ok(settingsControls.length > 0, "controls unsupported by the unavailable backend must render NOT AVAILABLE");
  });
});

test("no console errors: a full generate/play/feedback/compare pass leaves the console clean", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await goToPreview(page);
    await enterText(page, "Full pass, no console errors.");
    await clickGenerate(page);
    await page.evaluate(async () => {
      const ws = document.querySelector("avl-workspace-preview");
      const card = ws.shadowRoot.querySelector("avl-voice-preview-card");
      const audioPlayer = card.shadowRoot.querySelector("avl-voice-player").shadowRoot.querySelector("avl-audio-player");
      audioPlayer.shadowRoot.querySelectorAll("avl-button")[0].shadowRoot.querySelector("button").click();
      await new Promise((r) => setTimeout(r, 100));
      const form = ws.shadowRoot.querySelector("avl-preview-feedback-form");
      const uncertain = [...form.shadowRoot.querySelectorAll("avl-button")].find((b) => b.textContent.trim() === "Uncertain");
      uncertain.shadowRoot.querySelector("button").click();
    });
    await page.waitForTimeout(200);
    // withPage()'s own teardown asserts consoleErrors is empty; reaching
    // this point is the scenario itself.
  });
});
