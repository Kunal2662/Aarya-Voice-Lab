// Real Voice Model Engine milestone -- real-browser tests for the Models
// workspace's new "Voice Model Engine -- provider capability" panel.
// Same withServer/collectShadowText pattern as app-smoke.test.mjs.
import { test } from "node:test";
import assert from "node:assert/strict";
import { pathToFileURL, fileURLToPath } from "node:url";
import { readFile, writeFile, rm, mkdir } from "node:fs/promises";
import path from "node:path";
import { createStaticServer } from "../tools/serve.mjs";

const PLAYWRIGHT_INDEX = "/opt/node22/lib/node_modules/playwright/index.js";
const CHROMIUM_EXECUTABLE = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const HERE = path.dirname(fileURLToPath(import.meta.url));
const CAPABILITIES_PATH = path.join(HERE, "..", "contracts", "live", "voice_engine_capabilities.json");

async function loadPlaywright() {
  const mod = await import(pathToFileURL(PLAYWRIGHT_INDEX).href);
  return mod.default;
}

// VL-D17 -- mirrors claude-command-center.test.mjs's withFileAt() exactly:
// controls the live, gitignored voice_engine_capabilities.json snapshot
// for the duration of one test, restoring whatever was on disk before
// (or removing the file again if it didn't exist) afterward.
async function withCapabilitiesFile(content, fn) {
  let existedBefore = false;
  let priorContent = null;
  try {
    priorContent = await readFile(CAPABILITIES_PATH, "utf-8");
    existedBefore = true;
  } catch {
    existedBefore = false;
  }
  try {
    if (content === null) {
      await rm(CAPABILITIES_PATH, { force: true });
    } else {
      await mkdir(path.dirname(CAPABILITIES_PATH), { recursive: true });
      await writeFile(CAPABILITIES_PATH, content);
    }
    await fn();
  } finally {
    if (existedBefore) {
      await writeFile(CAPABILITIES_PATH, priorContent);
    } else {
      await rm(CAPABILITIES_PATH, { force: true });
    }
  }
}

// VL-D17 -- a realistic voice_engine_capabilities.json payload, mirroring
// scripts/export_voice_engine_capabilities.py's real envelope shape.
// `detail`/`missing_requirements` are the fields this milestone bridges;
// callers override them per scenario.
function realCapabilitiesFixture() {
  return {
    $generated_by: "scripts/export_voice_engine_capabilities.py",
    $live_snapshot: true,
    note: "Point-in-time capability detection for THIS interpreter, not a frozen contract or a promise about any other machine. Re-run this script to refresh.",
    embedding_providers: [
      { name: "synthetic-cosine-projection", is_synthetic: true, state: "SYNTHETIC_ONLY", detail: "" },
      { name: "local-neural-embedding", is_synthetic: false, state: "NOT_CONFIGURED", detail: "titanet_large loaded in 8.42s" },
    ],
    generation_provider: { name: "local-neural-voice-generator", backend_state: "NOT_CONFIGURED", compute_backend: "cpu", supported_controls: [] },
    training_provider: {
      name: "local-training-provider",
      state: "NOT_CONFIGURED",
      compute_backend: "cpu",
      missing_requirements: ["nemo_toolkit", "torch"],
      detail: "No real local training runtime is installed in this interpreter",
    },
  };
}

async function withModelsPageText(fn) {
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
      await page.goto(`${baseUrl}/app/index.html`, { waitUntil: "networkidle" });
      await page.evaluate(() => {
        location.hash = "#/models";
      });
      await page.waitForTimeout(300);
      const text = await collectShadowText(page, "avl-workspace-models");
      await fn(page, text, consoleErrors);
      await page.close();
    });
  } finally {
    await browser.close();
  }
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

test("VL-D12: Models workspace shows an honest model registry panel", { timeout: 30_000 }, async () => {
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
      assert.match(text, /Model registry \(real, checksum-addressed entries\)/);

      // Whatever the live-snapshot fetch outcome, the panel must say ONE
      // of these honest things -- never silently show nothing.
      const notFetched = /No live model registry snapshot fetched yet/.test(text);
      const empty = /No real \(non-private\) model is registered yet\./.test(text);
      const hasEntries = /\(1\.0\.0\)/.test(text) || /titanet_large/.test(text);
      assert.ok(
        notFetched || empty || hasEntries,
        `panel showed none of not-fetched/empty/real-entries: ${text}`,
      );

      // Never, under any live-snapshot outcome, does this panel mention
      // a private_voice entry -- see docs/SECURITY.md and
      // registry.ModelRegistry.list_non_private_models().
      assert.doesNotMatch(text, /private_voice/i);
      await page.close();
    });
  } finally {
    await browser.close();
  }
});

test("VL-D12: a real model registry entry renders its real lifecycle state, never a fabricated one", { timeout: 30_000 }, async () => {
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

      const registryBadges = await page.evaluate(() => {
        const ws = document.querySelector("avl-workspace-models");
        const panels = [...ws.shadowRoot.querySelectorAll("avl-panel")];
        const panel = panels.find((p) => p.getAttribute("title") === "Model registry (real, checksum-addressed entries)");
        if (!panel) return null;
        return [...panel.querySelectorAll("avl-status-badge")].map((b) => b.getAttribute("state"));
      });

      // If any registry entries were fetched, every lifecycle badge must
      // be a real value from the model_lifecycle vocabulary -- never a
      // blank, never a fabricated default.
      const VALID_LIFECYCLE_STATES = ["DRAFT", "TRAINING", "EVALUATING", "VALIDATED", "AVAILABLE", "ACTIVE", "ARCHIVED", "FAILED"];
      for (const state of registryBadges || []) {
        assert.ok(VALID_LIFECYCLE_STATES.includes(state), `unexpected model_lifecycle state: ${state}`);
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
      // status domain and a real state within it. VL-D12 added
      // model_lifecycle badges for the real model registry panel,
      // alongside the pre-existing engine-capability domains.
      for (const { domain, state } of badgeDomains) {
        assert.ok(
          ["training_provider_state", "generation_backend_state", "model_lifecycle"].includes(domain),
          `unexpected domain: ${domain}`,
        );
        assert.ok(state && state.length > 0, "badge must have a real state, never blank");
      }
      await page.close();
    });
  } finally {
    await browser.close();
  }
});

test("VL-D17: a real embedding provider's detail renders verbatim", { timeout: 30_000 }, async () => {
  const fixture = realCapabilitiesFixture();
  await withCapabilitiesFile(JSON.stringify(fixture), async () => {
    await withModelsPageText(async (page, text) => {
      assert.ok(text.includes("titanet_large loaded in 8.42s"), `expected provider detail not found: ${text}`);
    });
  });
});

test("VL-D17: multiple embedding providers render their own detail independently", { timeout: 30_000 }, async () => {
  const fixture = realCapabilitiesFixture();
  fixture.embedding_providers.push({
    name: "third-embedding-provider",
    is_synthetic: false,
    state: "NOT_CONFIGURED",
    detail: "no capability probe has run yet",
  });
  await withCapabilitiesFile(JSON.stringify(fixture), async () => {
    await withModelsPageText(async (page, text) => {
      assert.ok(text.includes("titanet_large loaded in 8.42s"), `first provider's detail missing: ${text}`);
      assert.ok(text.includes("no capability probe has run yet"), `second provider's detail missing: ${text}`);
      // The first (synthetic) provider's detail is "" in the fixture --
      // it must never fabricate the other providers' text in its place.
      assert.equal((text.match(/titanet_large loaded in 8\.42s/g) || []).length, 1, "each detail must render exactly once");
    });
  });
});

test("VL-D17: training provider detail renders verbatim", { timeout: 30_000 }, async () => {
  const fixture = realCapabilitiesFixture();
  await withCapabilitiesFile(JSON.stringify(fixture), async () => {
    await withModelsPageText(async (page, text) => {
      assert.ok(
        text.includes("No real local training runtime is installed in this interpreter"),
        `expected training detail not found: ${text}`,
      );
    });
  });
});

test("VL-D17: every training missing requirement renders", { timeout: 30_000 }, async () => {
  const fixture = realCapabilitiesFixture();
  fixture.training_provider.missing_requirements = ["nemo_toolkit", "torch", "sentencepiece"];
  await withCapabilitiesFile(JSON.stringify(fixture), async () => {
    await withModelsPageText(async (page, text) => {
      assert.match(text, /Missing requirements: nemo_toolkit, torch, sentencepiece\./);
    });
  });
});

test("VL-D17: empty missing_requirements produces no fabricated missing sentence", { timeout: 30_000 }, async () => {
  const fixture = realCapabilitiesFixture();
  fixture.training_provider.missing_requirements = [];
  await withCapabilitiesFile(JSON.stringify(fixture), async () => {
    await withModelsPageText(async (page, text) => {
      assert.doesNotMatch(text, /Missing requirements:/);
      // The training detail sentence is unrelated to missing_requirements
      // and must still render on its own.
      assert.ok(text.includes("No real local training runtime is installed in this interpreter"));
    });
  });
});

test("VL-D17: missing/null detail fields render safely, never a crash or fabricated placeholder", { timeout: 30_000 }, async () => {
  const fixture = realCapabilitiesFixture();
  fixture.embedding_providers[1].detail = null;
  delete fixture.training_provider.detail;
  fixture.training_provider.missing_requirements = null;
  await withCapabilitiesFile(JSON.stringify(fixture), async () => {
    await withModelsPageText(async (page, text, consoleErrors) => {
      assert.deepEqual(consoleErrors, [], `null/missing detail fields must not throw: ${JSON.stringify(consoleErrors)}`);
      // The row itself (name + badge) must still render normally.
      assert.match(text, /Embedding: local-neural-embedding/);
      assert.match(text, /Training: local-training-provider/);
      // Never a fabricated "null"/"undefined" string standing in for the
      // absent detail.
      assert.doesNotMatch(text, /\bnull\b/);
      assert.doesNotMatch(text, /\bundefined\b/);
      assert.doesNotMatch(text, /Missing requirements:/);
    });
  });
});

test("VL-D17: existing provider names and state/backend_state badges remain unchanged alongside the new detail lines", { timeout: 30_000 }, async () => {
  const fixture = realCapabilitiesFixture();
  await withCapabilitiesFile(JSON.stringify(fixture), async () => {
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

        const engineBadges = await page.evaluate(() => {
          const ws = document.querySelector("avl-workspace-models");
          const panels = [...ws.shadowRoot.querySelectorAll("avl-panel")];
          const panel = panels.find((p) => p.getAttribute("title") === "Voice Model Engine — provider capability");
          if (!panel) return null;
          return [...panel.querySelectorAll("avl-status-badge")].map((b) => ({
            domain: b.getAttribute("domain"),
            state: b.getAttribute("state"),
          }));
        });

        const text = await collectShadowText(page, "avl-workspace-models");
        assert.match(text, /Embedding: synthetic-cosine-projection/);
        assert.match(text, /Embedding: local-neural-embedding/);
        assert.match(text, /Generation: local-neural-voice-generator/);
        assert.match(text, /Training: local-training-provider/);
        // Exactly two badges in this panel: the one non-synthetic
        // embedding provider (the synthetic one gets the SYNTHETIC note
        // instead of a badge) plus generation, plus training -- three
        // total, each still carrying its real, pre-D17 state.
        assert.deepEqual(engineBadges, [
          { domain: "training_provider_state", state: "NOT_CONFIGURED" },
          { domain: "generation_backend_state", state: "NOT_CONFIGURED" },
          { domain: "training_provider_state", state: "NOT_CONFIGURED" },
        ]);
        await page.close();
      });
    } finally {
      await browser.close();
    }
  });
});

test("VL-D17: a missing voice_engine_capabilities snapshot preserves the existing 'not fetched yet' state", { timeout: 30_000 }, async () => {
  await withCapabilitiesFile(null, async () => {
    await withModelsPageText(async (page, text) => {
      assert.match(text, /No live capability snapshot fetched yet/);
      assert.doesNotMatch(text, /Missing requirements:/);
    });
  });
});

test("VL-D17: a malformed voice_engine_capabilities snapshot preserves the existing 'not fetched yet' state", { timeout: 30_000 }, async () => {
  await withCapabilitiesFile("{not valid json", async () => {
    await withModelsPageText(async (page, text, consoleErrors) => {
      assert.match(text, /No live capability snapshot fetched yet/);
      assert.deepEqual(consoleErrors, [], `malformed JSON must not throw an uncaught error: ${JSON.stringify(consoleErrors)}`);
    });
  });
});
