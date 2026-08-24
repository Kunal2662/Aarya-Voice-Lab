// Real-browser (headless Chromium) tests for VL-D10's Claude Command
// Center Bridge: the live command_center_snapshot() read wired into
// workspace-claude.js / claude-command-shell.js. Same withPage pattern
// as calibration.test.mjs/processing.test.mjs. This file directly
// controls frontend/contracts/live/command_center_snapshot.json (the
// same gitignored, point-in-time file
// scripts/export_command_center_snapshot.py writes) so it can exercise
// both the "snapshot available" and "snapshot missing/malformed" honest
// paths, restoring whatever was on disk before it ran.
import { test } from "node:test";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { readFile, writeFile, rm, mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createStaticServer } from "../tools/serve.mjs";

const PLAYWRIGHT_INDEX = "/opt/node22/lib/node_modules/playwright/index.js";
const CHROMIUM_EXECUTABLE = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const HERE = path.dirname(fileURLToPath(import.meta.url));
const SNAPSHOT_PATH = path.join(HERE, "..", "contracts", "live", "command_center_snapshot.json");
const IDENTITY_SNAPSHOT_PATH = path.join(HERE, "..", "contracts", "live", "identity_status_snapshot.json");

async function loadPlaywright() {
  const mod = await import(pathToFileURL(PLAYWRIGHT_INDEX).href);
  return mod.default;
}

function realSnapshotFixture() {
  return {
    $generated_by: "scripts/export_command_center_snapshot.py",
    $live_snapshot: true,
    note: "Point-in-time read of Git/audit-log state, not a frozen contract.",
    contract: "command_center_snapshot",
    contract_version: "1.0.0",
    processing_version: "0.1.0",
    repository: {
      contract: "repository_context",
      branch: "claude/phase3-speaker-verification",
      head: "1224407ae47f083ec17f076defa85b12e81e848a",
      head_short: "1224407",
      head_subject: "feat: implement local session persistence",
      working_tree_clean: false,
      changed_file_count: 5,
      recent_commits: ["1224407 feat: implement local session persistence"],
    },
    commands: {
      contract: "command_catalogue",
      commands: [
        { command: "system-info", summary: "Hardware and environment facts.", risk: "read_only", supports_json: true, requires_confirmation: false, gate_reason: null },
        { command: "train", summary: "PLANNED — not implemented.", risk: "gated", supports_json: true, requires_confirmation: false, gate_reason: "No voice model training exists in this project." },
      ],
      count: 2,
    },
    verification: {
      contract: "verification_commands",
      commands: [{ id: "tests", label: "Run test suite", command: ["python", "-m", "pytest", "-q"] }],
    },
    activity: {
      contract: "activity_feed",
      entries: [{ kind: "identity_review", summary: "identity_review · seg-test-1", timestamp: "2026-01-01T00:00:00Z", subject_id: "seg-test-1", detail: {} }],
      count: 1,
      total_available: 1,
      chain_intact: true,
    },
    diagnostics: {
      contract: "diagnostics",
      healthy: true,
      problems: [],
      git_safety_ok: true,
      audit_chain_intact: true,
      stages_implemented: 9,
      identity_boundary_stage: "speaker_enrollment",
      real_provider_installed: false,
      real_recordings_present: false,
    },
  };
}

async function withFileAt(filePath, content, fn) {
  let existedBefore = false;
  let priorContent = null;
  try {
    priorContent = await readFile(filePath, "utf-8");
    existedBefore = true;
  } catch {
    existedBefore = false;
  }
  try {
    if (content === null) {
      await rm(filePath, { force: true });
    } else {
      await mkdir(path.dirname(filePath), { recursive: true });
      await writeFile(filePath, content);
    }
    await fn();
  } finally {
    if (existedBefore) {
      await writeFile(filePath, priorContent);
    } else {
      await rm(filePath, { force: true });
    }
  }
}

async function withSnapshotFile(content, fn) {
  return withFileAt(SNAPSHOT_PATH, content, fn);
}

function realIdentitySnapshotFixture() {
  return {
    $generated_by: "scripts/export_identity_status_snapshot.py",
    $live_snapshot: true,
    note: "Point-in-time read of speaker-identity/enrollment/embedding state, not a frozen contract.",
    contract: "desktop_snapshot",
    contract_version: "1.0.0",
    processing_version: "0.1.0",
    profiles: { contract: "speaker_profiles", profiles: [], count: 2, usable_count: 1 },
    enrollment: {
      contract: "enrollment_status",
      by_state: {},
      by_role: {},
      available_strategies: [],
      available_providers: ["local-neural-embedding", "synthetic-cosine-projection"],
      real_provider_installed: true,
      note: "A real embedding provider is installed and loaded on this machine (see identity.embeddings.any_real_provider_available).",
    },
    pipeline: { contract: "pipeline_status", stages: [], identity_boundary_index: 5, identity_boundary_stage: "speaker_enrollment", batches: [], implemented_count: 9 },
    embeddings: {
      contract: "embedding_inventory",
      embedding_ids: [],
      count: 0,
      storage_directory: "data/embeddings",
      git_ignored: true,
      export_supported: false,
      note: "Vectors are never returned by any contract. Embeddings are biometric identifiers and have no export path.",
    },
    runtime: {
      contract: "runtime_capabilities",
      components: [
        { component: "synthetic-cosine-projection", runs_on_cpu: true, requires_accelerator: false },
        { component: "verification-engine", runs_on_cpu: true, requires_accelerator: false },
        { component: "local-neural-embedding", runs_on_cpu: true, requires_accelerator: false },
      ],
      portability: { cpu_only_viable: true, accelerator_bound_components: [], undetermined_components: [] },
    },
    preview: {
      contract: "voice_preview_status",
      iteration_count: 0,
      generation_implemented: false,
      note: "VL-V0 contracts only. No voice generation exists in Phase 3, and no generated speech has ever been produced by this project.",
    },
    audit: { entry_count: 4, event_counts: {}, chain_intact: true, chain_problems: [], first_entry: null, last_entry: null },
  };
}

async function withIdentitySnapshotFile(content, fn) {
  return withFileAt(IDENTITY_SNAPSHOT_PATH, content, fn);
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
    const LIVE_SNAPSHOT_SUFFIXES = [
      "/contracts/live/dataset_gate_status.json",
      "/contracts/live/command_center_snapshot.json",
      "/contracts/live/identity_status_snapshot.json",
    ];
    const unexpectedBadResponses = badResponseUrls.filter((url) => !LIVE_SNAPSHOT_SUFFIXES.some((suffix) => url.endsWith(suffix)));
    assert.deepEqual(unexpectedBadResponses, [], `unexpected failed requests: ${unexpectedBadResponses.join("; ")}`);
    const expectedErrorCount = badResponseUrls.length - unexpectedBadResponses.length;
    assert.equal(
      consoleErrors.length,
      expectedErrorCount,
      `console errors beyond the expected live-snapshot 404s: ${JSON.stringify(consoleErrors)}`,
    );
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
}

async function goToClaude(page) {
  await page.evaluate(() => {
    location.hash = "#/claude";
  });
  await page.waitForTimeout(250);
}

async function shellText(page) {
  return page.evaluate(() => {
    const ws = document.querySelector("avl-workspace-claude");
    const shell = ws.shadowRoot.querySelector("avl-claude-command-shell");
    return shell.shadowRoot.textContent;
  });
}

test("1. navigate to Claude workspace: it mounts with a real dashboard", { timeout: 30_000 }, async () => {
  await withSnapshotFile(JSON.stringify(realSnapshotFixture()), async () => {
    await withPage(async (page) => {
      await goToClaude(page);
      const workspaceTag = await page.evaluate(
        () => document.querySelector('avl-app-shell [slot="workspace"]').firstElementChild.tagName.toLowerCase(),
      );
      assert.equal(workspaceTag, "avl-workspace-claude");
    });
  });
});

test("2. live snapshot loads and the shell no longer says 'not fetched'", { timeout: 30_000 }, async () => {
  await withSnapshotFile(JSON.stringify(realSnapshotFixture()), async () => {
    await withPage(async (page) => {
      await goToClaude(page);
      const text = await shellText(page);
      assert.doesNotMatch(text, /not fetched/);
      assert.doesNotMatch(text, /-------/);
    });
  });
});

test("3. real branch is displayed", { timeout: 30_000 }, async () => {
  await withSnapshotFile(JSON.stringify(realSnapshotFixture()), async () => {
    await withPage(async (page) => {
      await goToClaude(page);
      const text = await shellText(page);
      assert.match(text, /claude\/phase3-speaker-verification/);
    });
  });
});

test("4. real HEAD is displayed", { timeout: 30_000 }, async () => {
  await withSnapshotFile(JSON.stringify(realSnapshotFixture()), async () => {
    await withPage(async (page) => {
      await goToClaude(page);
      const text = await shellText(page);
      assert.match(text, /1224407/);
    });
  });
});

test("5. real working-tree state is displayed", { timeout: 30_000 }, async () => {
  await withSnapshotFile(JSON.stringify(realSnapshotFixture()), async () => {
    await withPage(async (page) => {
      await goToClaude(page);
      const text = await shellText(page);
      assert.match(text, /5 changed/);
    });
  });
});

test("6. activity comes from the real snapshot, not a fabricated empty log", { timeout: 30_000 }, async () => {
  await withSnapshotFile(JSON.stringify(realSnapshotFixture()), async () => {
    await withPage(async (page) => {
      await goToClaude(page);
      // avl-claude-output-log has its own nested shadow root -- not
      // included in the shell's own shadowRoot.textContent.
      const text = await page.evaluate(() => {
        const ws = document.querySelector("avl-workspace-claude");
        const shell = ws.shadowRoot.querySelector("avl-claude-command-shell");
        const log = shell.shadowRoot.querySelector("avl-claude-output-log");
        return log.shadowRoot.textContent;
      });
      assert.match(text, /identity_review · seg-test-1/);
    });
  });
});

test("7. the real command catalogue renders, including a gated command's reason", { timeout: 30_000 }, async () => {
  await withSnapshotFile(JSON.stringify(realSnapshotFixture()), async () => {
    await withPage(async (page) => {
      await goToClaude(page);
      const text = await shellText(page);
      assert.match(text, /system-info/);
      assert.match(text, /No voice model training exists in this project\./);
    });
  });
});

test("8. real verification descriptors render", { timeout: 30_000 }, async () => {
  await withSnapshotFile(JSON.stringify(realSnapshotFixture()), async () => {
    await withPage(async (page) => {
      await goToClaude(page);
      const text = await shellText(page);
      assert.match(text, /Run test suite: python -m pytest -q/);
    });
  });
});

test("9. diagnostics render as healthy for a real healthy snapshot", { timeout: 30_000 }, async () => {
  await withSnapshotFile(JSON.stringify(realSnapshotFixture()), async () => {
    await withPage(async (page) => {
      await goToClaude(page);
      const text = await shellText(page);
      assert.match(text, /Diagnostics: healthy\./);
    });
  });
});

test("9b. diagnostics render as unhealthy honestly, never silently green", { timeout: 30_000 }, async () => {
  const unhealthy = realSnapshotFixture();
  unhealthy.diagnostics.healthy = false;
  unhealthy.diagnostics.problems = ["1 protected-material violation(s) in Git"];
  await withSnapshotFile(JSON.stringify(unhealthy), async () => {
    await withPage(async (page) => {
      await goToClaude(page);
      const text = await shellText(page);
      assert.match(text, /Diagnostics: unhealthy\./);
      assert.match(text, /1 protected-material violation\(s\) in Git/);
    });
  });
});

test("10. a missing snapshot remains honest: no fabricated branch/HEAD/activity", { timeout: 30_000 }, async () => {
  await withSnapshotFile(null, async () => {
    await withPage(async (page) => {
      await goToClaude(page);
      const text = await shellText(page);
      assert.match(text, /No repository context loaded/);
      assert.match(text, /Diagnostics unavailable/);
      assert.match(text, /No command catalogue loaded/);
      assert.doesNotMatch(text, /claude\/phase3-speaker-verification/);
    });
  });
});

test("11. a malformed snapshot file remains honest, same as a missing one", { timeout: 30_000 }, async () => {
  await withSnapshotFile("{not valid json", async () => {
    await withPage(async (page) => {
      await goToClaude(page);
      const text = await shellText(page);
      assert.match(text, /No repository context loaded/);
      assert.doesNotMatch(text, /claude\/phase3-speaker-verification/);
    });
  });
});

test("11b. a well-formed but wrong-contract snapshot file remains honest", { timeout: 30_000 }, async () => {
  await withSnapshotFile(JSON.stringify({ contract: "dataset_gate_status", access_allowed: true }), async () => {
    await withPage(async (page) => {
      await goToClaude(page);
      const text = await shellText(page);
      assert.match(text, /No repository context loaded/);
    });
  });
});

test("12. the Claude context preview carries real gitState when the snapshot is available", { timeout: 30_000 }, async () => {
  await withSnapshotFile(JSON.stringify(realSnapshotFixture()), async () => {
    await withPage(async (page) => {
      await goToClaude(page);
      const contextJson = await page.evaluate(() => {
        const ws = document.querySelector("avl-workspace-claude");
        const pre = ws.shadowRoot.querySelector("avl-panel pre");
        return pre.textContent;
      });
      const context = JSON.parse(contextJson);
      assert.deepEqual(context.git_state, {
        branch: "claude/phase3-speaker-verification",
        head_short: "1224407",
        working_tree_clean: false,
      });
    });
  });
});

async function identityPanelText(page) {
  // Stat tiles render their label/value inside their own shadow root, so
  // plain .textContent (light DOM only) misses them -- walk shadow trees
  // like voice-engine-status.test.mjs's collectShadowText().
  return page.evaluate(() => {
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
    const ws = document.querySelector("avl-workspace-claude");
    const panels = [...ws.shadowRoot.querySelectorAll("avl-panel")];
    const panel = panels.find((p) => p.getAttribute("title") === "Identity & enrollment status");
    return panel ? collect(panel) : null;
  });
}

test("14. a missing identity status snapshot renders an honest 'not fetched' state, never a fabricated count", { timeout: 30_000 }, async () => {
  await withSnapshotFile(JSON.stringify(realSnapshotFixture()), async () => {
    await withIdentitySnapshotFile(null, async () => {
      await withPage(async (page) => {
        await goToClaude(page);
        const text = await identityPanelText(page);
        assert.match(text, /No live identity status snapshot fetched yet/);
      });
    });
  });
});

test("15. a real identity status snapshot renders real profile/pipeline counts, not zeros", { timeout: 30_000 }, async () => {
  await withSnapshotFile(JSON.stringify(realSnapshotFixture()), async () => {
    await withIdentitySnapshotFile(JSON.stringify(realIdentitySnapshotFixture()), async () => {
      await withPage(async (page) => {
        await goToClaude(page);
        const text = await identityPanelText(page);
        assert.doesNotMatch(text, /No live identity status snapshot fetched yet/);
        assert.match(text, /\b2\b/); // profiles.count
        assert.match(text, /\b9\b/); // pipeline.implemented_count
        assert.match(text, /\b4\b/); // audit.entry_count
      });
    });
  });
});

test("16. real_provider_installed=true renders honestly, matching the real embedding-provider fix", { timeout: 30_000 }, async () => {
  const snapshot = realIdentitySnapshotFixture();
  snapshot.enrollment.real_provider_installed = true;
  await withSnapshotFile(JSON.stringify(realSnapshotFixture()), async () => {
    await withIdentitySnapshotFile(JSON.stringify(snapshot), async () => {
      await withPage(async (page) => {
        await goToClaude(page);
        const text = await identityPanelText(page);
        assert.match(text, /Real embedding provider installed on this machine\./);
      });
    });
  });
});

test("17. real_provider_installed=false renders honestly too -- this panel never assumes either direction", { timeout: 30_000 }, async () => {
  const snapshot = realIdentitySnapshotFixture();
  snapshot.enrollment.real_provider_installed = false;
  await withSnapshotFile(JSON.stringify(realSnapshotFixture()), async () => {
    await withIdentitySnapshotFile(JSON.stringify(snapshot), async () => {
      await withPage(async (page) => {
        await goToClaude(page);
        const text = await identityPanelText(page);
        assert.match(text, /No real embedding provider installed — synthetic only\./);
      });
    });
  });
});

test("18. VL-D13: runtime capability components render by name, including the real embedding provider when present", { timeout: 30_000 }, async () => {
  await withSnapshotFile(JSON.stringify(realSnapshotFixture()), async () => {
    await withIdentitySnapshotFile(JSON.stringify(realIdentitySnapshotFixture()), async () => {
      await withPage(async (page) => {
        await goToClaude(page);
        const text = await identityPanelText(page);
        assert.match(text, /synthetic-cosine-projection/);
        assert.match(text, /verification-engine/);
        assert.match(text, /local-neural-embedding/);
      });
    });
  });
});

test("19. VL-D13: a runtime snapshot with no real provider declared does not fabricate the local-neural-embedding component", { timeout: 30_000 }, async () => {
  const snapshot = realIdentitySnapshotFixture();
  snapshot.enrollment.real_provider_installed = false;
  snapshot.runtime.components = snapshot.runtime.components.filter((c) => c.component !== "local-neural-embedding");
  await withSnapshotFile(JSON.stringify(realSnapshotFixture()), async () => {
    await withIdentitySnapshotFile(JSON.stringify(snapshot), async () => {
      await withPage(async (page) => {
        await goToClaude(page);
        const text = await identityPanelText(page);
        assert.match(text, /synthetic-cosine-projection/);
        assert.doesNotMatch(text, /local-neural-embedding/);
      });
    });
  });
});

test("20. VL-D13: embedding inventory and preview-loop honesty sentences render, never a fabricated generated-speech claim", { timeout: 30_000 }, async () => {
  await withSnapshotFile(JSON.stringify(realSnapshotFixture()), async () => {
    await withIdentitySnapshotFile(JSON.stringify(realIdentitySnapshotFixture()), async () => {
      await withPage(async (page) => {
        await goToClaude(page);
        const text = await identityPanelText(page);
        assert.match(text, /Embeddings are biometric identifiers and have no export path\./);
        assert.match(text, /Voice generation is not implemented/);
      });
    });
  });
});

test("21. VL-D14: enrollment strategies render by name when declared", { timeout: 30_000 }, async () => {
  const snapshot = realIdentitySnapshotFixture();
  snapshot.enrollment.available_strategies = [
    { name: "synthetic", version: "1.0.0", requires_human_approval: false, permitted_roles: ["any"], minimum_samples: 1, minimum_total_seconds: 0.5 },
    { name: "direct_recording", version: "1.0.0", requires_human_approval: true, permitted_roles: ["operator"], minimum_samples: 3, minimum_total_seconds: 5.0 },
    { name: "human_anchored", version: "1.0.0", requires_human_approval: true, permitted_roles: ["target"], minimum_samples: 3, minimum_total_seconds: 5.0 },
  ];
  await withSnapshotFile(JSON.stringify(realSnapshotFixture()), async () => {
    await withIdentitySnapshotFile(JSON.stringify(snapshot), async () => {
      await withPage(async (page) => {
        await goToClaude(page);
        const text = await identityPanelText(page);
        assert.match(text, /Enrollment strategies available: synthetic, direct_recording, human_anchored\./);
      });
    });
  });
});

test("22. VL-D14: embedding providers render by name", { timeout: 30_000 }, async () => {
  await withSnapshotFile(JSON.stringify(realSnapshotFixture()), async () => {
    await withIdentitySnapshotFile(JSON.stringify(realIdentitySnapshotFixture()), async () => {
      await withPage(async (page) => {
        await goToClaude(page);
        const text = await identityPanelText(page);
        assert.match(text, /Embedding providers available: local-neural-embedding, synthetic-cosine-projection\./);
      });
    });
  });
});

test("23. VL-D14: empty enrollment strategies/providers render an honest 'none declared' state, never fabricated", { timeout: 30_000 }, async () => {
  // Note: runtime.components (a separate, unrelated field bridged by
  // D13) still legitimately contains "synthetic-cosine-projection" in
  // this fixture -- so this test asserts on the enrollment sentences
  // specifically, not on bare substring absence, to avoid a false
  // failure from that unrelated row.
  const snapshot = realIdentitySnapshotFixture();
  snapshot.enrollment.available_strategies = [];
  snapshot.enrollment.available_providers = [];
  await withSnapshotFile(JSON.stringify(realSnapshotFixture()), async () => {
    await withIdentitySnapshotFile(JSON.stringify(snapshot), async () => {
      await withPage(async (page) => {
        await goToClaude(page);
        const text = await identityPanelText(page);
        assert.match(text, /No enrollment strategies declared\./);
        assert.match(text, /No embedding providers declared\./);
        assert.doesNotMatch(text, /Enrollment strategies available:/);
        assert.doesNotMatch(text, /Embedding providers available:/);
      });
    });
  });
});

test("24. VL-D15: real batch ids on disk render verbatim", { timeout: 30_000 }, async () => {
  const snapshot = realIdentitySnapshotFixture();
  snapshot.pipeline.batches = ["batch-001", "batch-002"];
  await withSnapshotFile(JSON.stringify(realSnapshotFixture()), async () => {
    await withIdentitySnapshotFile(JSON.stringify(snapshot), async () => {
      await withPage(async (page) => {
        await goToClaude(page);
        const text = await identityPanelText(page);
        assert.match(text, /Batches on disk: batch-001, batch-002\./);
      });
    });
  });
});

test("25. VL-D15: no batches recorded renders an honest empty state, never fabricated", { timeout: 30_000 }, async () => {
  // The shared fixture already defaults pipeline.batches to [] -- this
  // asserts that default renders honestly rather than a fabricated id.
  await withSnapshotFile(JSON.stringify(realSnapshotFixture()), async () => {
    await withIdentitySnapshotFile(JSON.stringify(realIdentitySnapshotFixture()), async () => {
      await withPage(async (page) => {
        await goToClaude(page);
        const text = await identityPanelText(page);
        assert.match(text, /No batches recorded yet\./);
        assert.doesNotMatch(text, /Batches on disk:/);
      });
    });
  });
});

test("26. VL-D15: the Identity panel's batch row never renders the synthetic Batches workspace's fixture data", { timeout: 30_000 }, async () => {
  const snapshot = realIdentitySnapshotFixture();
  snapshot.pipeline.batches = ["batch-001", "batch-002"];
  await withSnapshotFile(JSON.stringify(realSnapshotFixture()), async () => {
    await withIdentitySnapshotFile(JSON.stringify(snapshot), async () => {
      await withPage(async (page) => {
        await goToClaude(page);
        const text = await identityPanelText(page);
        assert.match(text, /Batches on disk: batch-001, batch-002\./);
        // avl-workspace-batches (a separate, unrelated workspace) renders
        // "synthetic-batch-NNN" ids from state/synthetic-fixtures.js's
        // syntheticBatches() -- this real, desktop_snapshot()-backed row
        // must never leak that fabricated data in, and must never be
        // confused with it.
        assert.doesNotMatch(text, /synthetic-batch/);
      });
    });
  });
});

test("13. a full create-then-navigate cycle across snapshot states produces zero console errors", { timeout: 30_000 }, async () => {
  await withSnapshotFile(JSON.stringify(realSnapshotFixture()), async () => {
    await withPage(async (page) => {
      await goToClaude(page);
      await page.evaluate(() => {
        location.hash = "#/command-center";
      });
      await page.waitForTimeout(200);
      await goToClaude(page);
      // withPage()'s own teardown asserts the expected (zero-beyond-
      // documented-404) console error count.
    });
  });
});
